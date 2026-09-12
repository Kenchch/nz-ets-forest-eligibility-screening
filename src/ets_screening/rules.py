"""Pure, auditable rule evaluation for open-data screening."""

from __future__ import annotations

from dataclasses import dataclass, field

import geopandas as gpd
import pandas as pd

from .geometry import compare_width_methods
from .load import assert_nztm2000, validate_candidates, validate_geometry


@dataclass(frozen=True)
class RuleConfig:
    minimum_area_ha: float = 1.0
    width_threshold_m: float = 30.0
    minimum_overlap_area_m2: float = 1.0
    minimum_overlap_pct: float = 1.0
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


def _overlap_metrics(
    frame: gpd.GeoDataFrame, overlay: gpd.GeoDataFrame
) -> tuple[pd.Series, pd.Series]:
    """Return true polygon-overlap area and candidate-area proportion.

    Boundary-only contact has zero area and must not fail R-03/R-04. Candidate
    overlay features are locally unioned before intersection so overlapping
    source records are not double-counted.
    """

    if overlay.empty:
        zeros = pd.Series(0.0, index=frame.index, dtype=float)
        return zeros, zeros.copy()
    index = overlay.sindex
    areas: list[float] = []
    for geometry in frame.geometry:
        positions = index.query(geometry, predicate="intersects")
        if len(positions) == 0:
            areas.append(0.0)
            continue
        target = overlay.geometry.iloc[positions].union_all()
        areas.append(float(geometry.intersection(target).area))
    area = pd.Series(areas, index=frame.index, dtype=float)
    proportion = area / frame.geometry.area
    return area, proportion.fillna(0.0)


def _join_rule_ids(row: pd.Series, columns: list[tuple[str, str]]) -> str:
    return "|".join(rule_id for rule_id, column in columns if not bool(row[column]))


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
    widths = compare_width_methods(out, config.width_threshold_m).set_index("unit_id")
    out["width_ap_m"] = out["unit_id"].astype(str).map(widths["width_area_perimeter_m"])
    out["width_ap_pass"] = out["unit_id"].astype(str).map(widths["area_perimeter_pass"])
    out["width_core_pass"] = out["unit_id"].astype(str).map(widths["erosion_core_pass"])
    out["width_methods_disagree"] = out["unit_id"].astype(str).map(widths["methods_disagree"])

    out["r01_area_pass"] = raw_area_ha >= config.minimum_area_ha
    # Erosion is the primary narrow-strip screen, but either-method disagreement
    # is conservatively escalated instead of silently promoted as a candidate.
    out["r02_width_proxy_pass"] = out["width_core_pass"] & ~out["width_methods_disagree"]
    pre1990_area, pre1990_ratio = _overlap_metrics(out, pre1990)
    conservation_area, conservation_ratio = _overlap_metrics(out, conservation)
    out["pre1990_overlap_m2"] = pre1990_area.round(2)
    out["pre1990_overlap_pct"] = (pre1990_ratio * 100).round(4)
    out["conservation_overlap_m2"] = conservation_area.round(2)
    out["conservation_overlap_pct"] = (conservation_ratio * 100).round(4)
    pre1990_material = (
        (pre1990_area > config.minimum_overlap_area_m2)
        & (pre1990_ratio * 100 >= config.minimum_overlap_pct)
    )
    conservation_material = (
        (conservation_area > config.minimum_overlap_area_m2)
        & (conservation_ratio * 100 >= config.minimum_overlap_pct)
    )
    out["r03_no_pre1990_overlap"] = ~pre1990_material
    out["r04_no_conservation_overlap"] = ~conservation_material
    out["advisory_rule_ids"] = ""
    out.loc[
        (pre1990_area > config.minimum_overlap_area_m2) & ~pre1990_material,
        "advisory_rule_ids",
    ] = "R-03-low-overlap"
    r04_minor = (conservation_area > config.minimum_overlap_area_m2) & ~conservation_material
    out.loc[r04_minor, "advisory_rule_ids"] = out.loc[r04_minor, "advisory_rule_ids"].map(
        lambda value: "|".join(filter(None, (value, "R-04-low-overlap")))
    )
    out["r05_lcdb_proxy_pass"] = out["lcdb_class"].isin(config.plantable_lcdb_classes)

    automated = [
        ("R-01", "r01_area_pass"),
        ("R-02", "r02_width_proxy_pass"),
        ("R-03", "r03_no_pre1990_overlap"),
        ("R-04", "r04_no_conservation_overlap"),
        ("R-05", "r05_lcdb_proxy_pass"),
    ]
    out["failed_rule_ids"] = out.apply(lambda row: _join_rule_ids(row, automated), axis=1)
    out["manual_review_rule_ids"] = "R-03|R-06|R-07|R-08"
    out["status"] = "candidate_review"
    out.loc[out["failed_rule_ids"] != "", "status"] = "quarantine"
    out.loc[~out["r04_no_conservation_overlap"], "status"] = "excluded"

    long_rows: list[dict[str, object]] = []
    rule_meta = {
        "R-01": ("Area at least 1 ha", "r01_area_pass", "area_ha"),
        "R-02": ("30 m width erosion proxy", "r02_width_proxy_pass", "width_core_pass"),
        "R-03": ("No material mapped pre-1990 overlap", "r03_no_pre1990_overlap", "r03_no_pre1990_overlap"),
        "R-04": ("No material public conservation overlap", "r04_no_conservation_overlap", "r04_no_conservation_overlap"),
        "R-05": ("Plantable LCDB proxy class", "r05_lcdb_proxy_pass", "lcdb_class"),
    }
    for _, row in out.iterrows():
        for rule_id, (name, passed_col, observed_col) in rule_meta.items():
            long_rows.append(
                {
                    "unit_id": row["unit_id"],
                    "rule_id": rule_id,
                    "rule_name": name,
                    "testable_from_open_data": True,
                    "passed": bool(row[passed_col]),
                    "observed": row[observed_col],
                }
            )
        for rule_id, name in (
            ("R-06", "Forest species"),
            ("R-07", "Crown cover at maturity"),
            ("R-08", "Height at maturity"),
        ):
            long_rows.append(
                {
                    "unit_id": row["unit_id"],
                    "rule_id": rule_id,
                    "rule_name": name,
                    "testable_from_open_data": False,
                    "passed": pd.NA,
                    "observed": "manual evidence required",
                }
            )
    return out, pd.DataFrame(long_rows)
