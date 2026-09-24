"""Pure, auditable rule evaluation for open-data screening."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from importlib import resources
from numbers import Real

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely.geometry.base import BaseGeometry

from .geometry import compare_width_methods
from .load import assert_nztm2000, validate_candidates, validate_geometry

#: Rules the pipeline evaluates, in audit-table order. Every other register
#: row is carried forward as a manual assessor check.
AUTOMATED_RULE_IDS = ("R-01", "R-02", "R-03", "R-04", "R-05")
TESTABILITY_LEVELS = ("yes", "proxy", "partial", "no")
REGISTER_COLUMNS = (
    "rule_id",
    "name",
    "source_clause",
    "source_url",
    "testable_from_open_data",
    "implementation",
    "failure_action",
)
#: A unit that passes R-01 by less than this fraction of the threshold is
#: flagged: a mean boundary shift of about 1 m moves a 1 ha unit by ~5%.
NEAR_THRESHOLD_FRACTION = 0.05


def load_rule_register() -> pd.DataFrame:
    """Return the packaged rule register, the single source of rule metadata."""

    with resources.files(__package__).joinpath("rule_register.csv").open(encoding="utf-8") as handle:
        register = pd.read_csv(handle, dtype=str, keep_default_na=False)
    if tuple(register.columns) != REGISTER_COLUMNS:
        raise ValueError(f"rule register columns must be {REGISTER_COLUMNS}")
    if register["rule_id"].duplicated().any():
        raise ValueError("rule register contains duplicate rule_id values")
    unknown = set(register["testable_from_open_data"]) - set(TESTABILITY_LEVELS)
    if unknown:
        raise ValueError(f"unknown testability levels in rule register: {sorted(unknown)}")
    indexed = register.set_index("rule_id")
    for rule_id in AUTOMATED_RULE_IDS:
        if rule_id not in indexed.index or indexed.loc[rule_id, "testable_from_open_data"] == "no":
            raise ValueError(f"rule register must list automated rule {rule_id} as testable")
    return register


def manual_review_rule_ids(register: pd.DataFrame | None = None) -> list[str]:
    """Rules an assessor must still decide: partially testable or not testable."""

    register = load_rule_register() if register is None else register
    manual = register["testable_from_open_data"].isin(["partial", "no"])
    return register.loc[manual, "rule_id"].tolist()


@dataclass(frozen=True)
class RuleConfig:
    minimum_area_ha: float = 1.0
    width_threshold_m: float = 30.0
    minimum_overlap_area_m2: float = 1.0
    minimum_overlap_pct: float = 1.0
    #: An overlap this large is never treated as mapping noise, whatever share
    #: of the unit it is: LCDB units reach 36,801 ha, so 1% alone waved through
    #: hundreds of hectares of conflict as a minor advisory. Such a unit stays
    #: in review only with a clip-required flag, and the conflict is removed
    #: from its conflict-free area. The default equals the statutory 1 ha.
    clip_required_overlap_m2: float = 10_000.0
    #: Overlap narrower than this is removed by morphological opening before
    #: materiality is judged. It matches the 15 m simplification of the LCDB
    #: mirror, so generalisation slivers cannot exclude a unit. 0 disables it.
    sliver_width_m: float = 15.0
    #: Plantable units closer than this are treated as one contiguous area for
    #: the R-01/R-02 contiguity routes, after MPI's 15 m adjacency guidance.
    adjacency_distance_m: float = 15.0
    plantable_lcdb_classes: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                "High Producing Exotic Grassland",
                "Low Producing Grassland",
                "Gorse and/or Broom",
                "Mixed Exotic Shrubland",
                "Bare or Lightly Vegetated Surfaces",
            }
        )
    )

    def __post_init__(self) -> None:
        for name in (
            "minimum_area_ha",
            "width_threshold_m",
            "minimum_overlap_area_m2",
            "minimum_overlap_pct",
            "clip_required_overlap_m2",
            "sliver_width_m",
            "adjacency_distance_m",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
                raise ValueError(f"{name} must be a finite number")
            if name in {"minimum_area_ha", "width_threshold_m"}:
                if value <= 0:
                    raise ValueError(f"{name} must be greater than zero")
            elif value < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.minimum_overlap_pct > 100:
            raise ValueError("minimum_overlap_pct must be between 0 and 100")

    def as_record(self) -> dict[str, object]:
        """Return a JSON-serialisable copy for run manifests."""

        record = asdict(self)
        record["plantable_lcdb_classes"] = sorted(self.plantable_lcdb_classes)
        return record


def _remove_slivers(overlap: BaseGeometry, width_m: float) -> BaseGeometry:
    """Drop parts of an overlap narrower than `width_m` (morphological opening).

    Mitred joins restore right-angled corners exactly, so a genuine square
    overlap keeps its full area; the final intersection keeps the result
    inside the original overlap.
    """

    # Intersections can carry stray lines and points from shared edges, and a
    # mixed collection cannot enter a further overlay operation.
    parts = [part for part in shapely.get_parts(overlap) if part.geom_type in ("Polygon", "MultiPolygon")]
    polygonal = shapely.union_all(parts) if parts else shapely.Polygon()
    if width_m <= 0 or polygonal.is_empty:
        return polygonal
    radius = width_m / 2.0
    opened = polygonal.buffer(-radius, join_style="mitre").buffer(radius, join_style="mitre")
    return polygonal.intersection(opened)


def _overlap_metrics(
    frame: gpd.GeoDataFrame, overlay: gpd.GeoDataFrame, sliver_width_m: float
) -> tuple[pd.Series, gpd.GeoSeries]:
    """Return raw overlap areas and sliver-filtered overlap geometries.

    Boundary-only contact has zero area and must not fail R-03/R-04. Candidate
    overlay features are locally unioned before intersection so overlapping
    source records are not double-counted.
    """

    empty = shapely.Polygon()
    if overlay.empty:
        zeros = pd.Series(0.0, index=frame.index, dtype=float)
        return zeros, gpd.GeoSeries([empty] * len(frame), index=frame.index, crs=frame.crs)
    index = overlay.sindex
    raw: list[float] = []
    core: list[BaseGeometry] = []
    for geometry in frame.geometry:
        positions = index.query(geometry, predicate="intersects")
        if len(positions) == 0:
            raw.append(0.0)
            core.append(empty)
            continue
        target = overlay.geometry.iloc[positions].union_all()
        overlap = geometry.intersection(target)
        raw.append(float(overlap.area))
        core.append(_remove_slivers(overlap, sliver_width_m))
    return (
        pd.Series(raw, index=frame.index, dtype=float),
        gpd.GeoSeries(core, index=frame.index, crs=frame.crs),
    )


def _adjacency_blocks(geometries: gpd.GeoSeries, eligible: np.ndarray, distance_m: float) -> np.ndarray:
    """Label eligible features joined by chains of gaps within `distance_m`.

    Ineligible features get -1. Labels are the smallest member position, so
    they do not depend on the traversal order.
    """

    labels = np.full(len(geometries), -1, dtype=np.int64)
    members = np.flatnonzero(eligible)
    if len(members) == 0:
        return labels
    subset = geometries.values[members]
    tree = shapely.STRtree(subset)
    left, right = tree.query(subset, predicate="dwithin", distance=distance_m)
    parent = np.arange(len(members))

    def find(item: int) -> int:
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    for a, b in zip(left.tolist(), right.tolist()):
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            parent[max(root_a, root_b)] = min(root_a, root_b)
    roots = np.array([find(item) for item in range(len(members))])
    labels[members] = members[roots]
    return labels


def _append_flag(flags: pd.Series, mask: pd.Series, flag: str) -> pd.Series:
    flags = flags.copy()
    flags[mask] = flags[mask].map(lambda value: "|".join(filter(None, (value, flag))))
    return flags


def candidate_advisory_mask(results: pd.DataFrame) -> pd.Series:
    """Candidates that passed screening while carrying an advisory flag."""

    return (results["status"] == "candidate_review") & results["advisory_rule_ids"].fillna("").ne("")


def _rule_names(register: pd.DataFrame, config: RuleConfig) -> dict[str, str]:
    names = register.set_index("rule_id")["name"].to_dict()
    defaults = RuleConfig()
    if config.minimum_area_ha != defaults.minimum_area_ha:
        names["R-01"] += f" (configured: {config.minimum_area_ha:g} ha)"
    if config.width_threshold_m != defaults.width_threshold_m:
        names["R-02"] += f" (configured: {config.width_threshold_m:g} m)"
    return names


def _overlap_observation(prefix: str, out: pd.DataFrame) -> pd.Series:
    return (
        "overlap_m2=" + out[f"{prefix}_overlap_m2"].map("{:.2f}".format)
        + "; overlap_pct=" + out[f"{prefix}_overlap_pct"].map("{:.4f}".format)
        + "; sliver_filtered_m2=" + out[f"{prefix}_overlap_core_m2"].map("{:.2f}".format)
    )


def _audit_table(out: gpd.GeoDataFrame, config: RuleConfig) -> pd.DataFrame:
    register = load_rule_register()
    names = _rule_names(register, config)
    testable = register.set_index("rule_id")["testable_from_open_data"].to_dict()
    advisory = out["advisory_rule_ids"].fillna("")
    contiguous = out["contiguous_plantable_ha"].map(
        lambda value: "none" if pd.isna(value) else f"{value:.4f}"
    )
    observed = {
        "R-01": "area_ha=" + out["area_ha"].map("{:.4f}".format) + "; contiguous_plantable_ha=" + contiguous,
        "R-02": (
            "equivalent_rectangle_m=" + out["width_rect_m"].map("{:.3f}".format)
            + "; erosion_core=" + out["width_core_pass"].map(lambda value: "yes" if value else "no")
            + "; area_perimeter_m=" + out["width_ap_m"].map("{:.3f}".format)
        ),
        "R-03": _overlap_observation("pre1990", out),
        "R-04": _overlap_observation("conservation", out),
        "R-05": out["lcdb_class"].astype(str),
    }
    failed = {
        "R-01": ~(out["r01_area_pass"] | out["r01_contiguous_pass"]),
        "R-02": ~(out["r02_width_proxy_pass"] | out["r02_contiguous_pass"]),
        "R-03": ~out["r03_no_pre1990_overlap"],
        "R-04": ~out["r04_no_conservation_overlap"],
        "R-05": ~out["r05_lcdb_proxy_pass"],
    }
    order = {rule_id: position for position, rule_id in enumerate(register["rule_id"])}
    frames = []
    for rule_id in register["rule_id"]:
        if rule_id in AUTOMATED_RULE_IDS:
            flagged = advisory.str.contains(f"{rule_id}-", regex=False)
            outcome = np.where(failed[rule_id], "fail", np.where(flagged, "advisory", "pass"))
            passed = pd.array(
                np.where(outcome == "advisory", None, outcome == "pass"), dtype="boolean"
            )
            rule_observed = observed[rule_id].to_numpy()
        else:
            outcome = np.full(len(out), "manual")
            passed = pd.array([pd.NA] * len(out), dtype="boolean")
            rule_observed = np.full(len(out), "manual evidence required")
        frames.append(
            pd.DataFrame(
                {
                    "unit_id": out["unit_id"].to_numpy(),
                    "rule_id": rule_id,
                    "rule_name": names[rule_id],
                    "testable_from_open_data": testable[rule_id],
                    "outcome": outcome,
                    "passed": passed,
                    "observed": rule_observed,
                    "_unit": np.arange(len(out)),
                    "_rule": order[rule_id],
                }
            )
        )
    audit = pd.concat(frames, ignore_index=True)
    audit = audit.sort_values(["_unit", "_rule"], kind="mergesort")
    return audit.drop(columns=["_unit", "_rule"]).reset_index(drop=True)


def evaluate_rules(
    candidates: gpd.GeoDataFrame,
    pre1990: gpd.GeoDataFrame,
    conservation: gpd.GeoDataFrame,
    config: RuleConfig | None = None,
) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    """Evaluate automated rules and return wide features plus a long audit table."""

    config = config or RuleConfig()
    validate_candidates(candidates)
    for name, frame in (("pre1990", pre1990), ("conservation", conservation)):
        assert_nztm2000(frame, name)
        if not frame.empty:
            validate_geometry(frame, name)

    out = candidates.copy()
    raw_area_ha = out.geometry.area / 10_000.0
    out["area_ha"] = raw_area_ha.round(4)
    # Assign by position: unit_id is validated unique as text, but mapping by
    # label would still misalign if a caller's index were not the default.
    widths = compare_width_methods(out, config.width_threshold_m)
    out["width_ap_m"] = widths["width_area_perimeter_m"].to_numpy()
    out["width_ap_pass"] = widths["area_perimeter_pass"].to_numpy()
    out["width_rect_m"] = widths["width_equivalent_rectangle_m"].to_numpy()
    out["width_rect_pass"] = widths["equivalent_rectangle_pass"].to_numpy()
    out["width_core_pass"] = widths["erosion_core_pass"].to_numpy()
    out["width_methods_disagree"] = widths["methods_disagree"].to_numpy()

    out["r01_area_pass"] = raw_area_ha >= config.minimum_area_ha
    # Both proxies must pass. A surviving core alone shows only that the unit
    # is 30 m wide somewhere; the equivalent rectangle carries the average.
    out["r02_width_proxy_pass"] = out["width_core_pass"] & out["width_rect_pass"]

    unit_area = out.geometry.area
    low_overlap = {}
    clip_required = {}
    cores = {}
    for prefix, overlay in (("pre1990", pre1990), ("conservation", conservation)):
        raw, core_geometry = _overlap_metrics(out, overlay, config.sliver_width_m)
        core = core_geometry.area
        cores[prefix] = core_geometry
        core_pct = (core / unit_area * 100).fillna(0.0)
        out[f"{prefix}_overlap_m2"] = raw.round(2)
        out[f"{prefix}_overlap_pct"] = (raw / unit_area * 100).fillna(0.0).round(4)
        out[f"{prefix}_overlap_core_m2"] = core.round(2)
        material = (core > config.minimum_overlap_area_m2) & (core_pct >= config.minimum_overlap_pct)
        out[f"{prefix}_material"] = material
        clip_required[prefix] = ~material & (core >= config.clip_required_overlap_m2)
        out[f"{prefix}_clip_required"] = clip_required[prefix]
        low_overlap[prefix] = (raw > config.minimum_overlap_area_m2) & ~material & ~clip_required[prefix]
    # Area left once every mapped conflict (after sliver removal) is taken
    # out. For a clip-required unit this, not the unit area, is the land still
    # open to review.
    conflicts = [
        a.union(b) if not a.is_empty and not b.is_empty else (b if a.is_empty else a)
        for a, b in zip(cores["pre1990"], cores["conservation"])
    ]
    conflict_area = gpd.GeoSeries(conflicts, index=out.index, crs=out.crs).area
    out["conflict_free_area_ha"] = ((unit_area - conflict_area).clip(lower=0) / 10_000.0).round(4)
    out["r03_no_pre1990_overlap"] = ~out["pre1990_material"]
    out["r04_no_conservation_overlap"] = ~out["conservation_material"]

    # Match on a case- and whitespace-normalised form. A bare `isin` treats
    # "Low Producing Grassland " or a differently-cased source field as a
    # non-plantable class and quarantines the unit with no warning, which is
    # indistinguishable from a real R-05 failure.
    allowed = {value.strip().casefold() for value in config.plantable_lcdb_classes}
    out["r05_lcdb_proxy_pass"] = out["lcdb_class"].astype(str).str.strip().str.casefold().isin(allowed)

    # Forest land is an area of land, not a land-cover mapping unit. Units that
    # are plantable and free of material conflicts are grouped when their gaps
    # are within the adjacency distance, so a unit can meet R-01 or R-02
    # through its neighbours instead of being judged alone.
    eligible = (out["r05_lcdb_proxy_pass"] & out["r03_no_pre1990_overlap"] & out["r04_no_conservation_overlap"]).to_numpy()
    blocks = pd.Series(_adjacency_blocks(out.geometry, eligible, config.adjacency_distance_m), index=out.index)
    in_block = blocks >= 0
    block_area_ha = raw_area_ha.groupby(blocks).transform("sum")
    anchor = in_block & out["r01_area_pass"] & out["r02_width_proxy_pass"]
    block_has_anchor = anchor.groupby(blocks).transform("any")
    out["contiguous_plantable_ha"] = block_area_ha.where(in_block).round(4)
    out["r01_contiguous_pass"] = in_block & ~out["r01_area_pass"] & (block_area_ha >= config.minimum_area_ha)
    out["r02_contiguous_pass"] = in_block & ~out["r02_width_proxy_pass"] & block_has_anchor

    flags = pd.Series("", index=out.index, dtype=object)
    near = out["r01_area_pass"] & (raw_area_ha < config.minimum_area_ha * (1 + NEAR_THRESHOLD_FRACTION))
    flags = _append_flag(flags, near, "R-01-near-threshold")
    flags = _append_flag(flags, out["r01_contiguous_pass"], "R-01-contiguous")
    flags = _append_flag(flags, out["r02_contiguous_pass"], "R-02-contiguous")
    flags = _append_flag(flags, clip_required["pre1990"], "R-03-clip-required")
    flags = _append_flag(flags, low_overlap["pre1990"], "R-03-low-overlap")
    flags = _append_flag(flags, clip_required["conservation"], "R-04-clip-required")
    flags = _append_flag(flags, low_overlap["conservation"], "R-04-low-overlap")
    out["advisory_rule_ids"] = flags

    failed = pd.DataFrame(
        {
            "R-01": ~(out["r01_area_pass"] | out["r01_contiguous_pass"]),
            "R-02": ~(out["r02_width_proxy_pass"] | out["r02_contiguous_pass"]),
            "R-03": ~out["r03_no_pre1990_overlap"],
            "R-04": ~out["r04_no_conservation_overlap"],
            "R-05": ~out["r05_lcdb_proxy_pass"],
        },
        index=out.index,
    )
    out["failed_rule_ids"] = failed.apply(lambda row: "|".join(row.index[row.to_numpy()]), axis=1)
    out["manual_review_rule_ids"] = "|".join(manual_review_rule_ids())
    out["status"] = "candidate_review"
    out.loc[out["failed_rule_ids"] != "", "status"] = "quarantine"
    out.loc[~out["r04_no_conservation_overlap"], "status"] = "excluded"
    return out, _audit_table(out, config)
