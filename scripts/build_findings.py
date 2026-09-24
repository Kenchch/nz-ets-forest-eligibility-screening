"""Build the evidence-backed Gisborne findings from committed inputs and outputs."""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from ets_screening.geometry import EROSION_TOLERANCE_M
from ets_screening.report import PNG_METADATA
from ets_screening.review_labels import load_review_labels, load_review_sample_ids
from ets_screening.rules import candidate_advisory_mask
from ets_screening.screen import SCOPE


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed" / "gisborne_candidates.gpkg"
OUTPUT = ROOT / "outputs" / "gisborne"
HALF_WIDTH_M = 15.0
#: Fragment sizes for the multi-lobe sensitivity count; not thresholds of law.
LOBE_SIZES_M2 = (500, 1000)
#: The unit inset in the ArcGIS Pro layout; arcgis/build_layout.py reads its
#: measurements from findings.json rather than hard-coding them.
LAYOUT_INSET_UNIT = "lcdb1000453434"


def _visual_review_findings(review_dir: Path) -> dict[str, object]:
    """Report the imagery review only when a named person has completed it.

    Until then the findings record the pending state rather than a rate, so no
    accuracy number in this repository can be read as the author's own imagery
    interpretation when it is not.
    """

    expected = load_review_sample_ids(review_dir / "review_sample_ids.csv")
    labels_path = review_dir / "review_labels.csv"
    if not labels_path.exists():
        return {
            "visual_review_status": "pending_independent_human_review",
            "visual_review_sample_size": int(len(expected)),
            "visual_review_labels_recorded": 0,
        }
    labels = load_review_labels(labels_path, expected)
    counts = labels["review_label"].value_counts()
    plausible = int(counts.get("plausible-plantable", 0))
    reviewers = sorted(set(labels["reviewer"]))
    return {
        "visual_review_status": "complete",
        "visual_review_sample_size": int(len(expected)),
        "visual_review_labels_recorded": int(len(labels)),
        "visual_plausible_plantable": plausible,
        "visual_already_forested": int(counts.get("already-forested", 0)),
        "visual_clearly_not_plantable": int(counts.get("clearly-not-plantable", 0)),
        "visual_agreement_rate": round(plausible / len(labels), 4),
        "visual_reviewer": "; ".join(reviewers),
        "visual_review_limitation": (
            f"{len(reviewers)}-reviewer interpretation of one imagery date; no ground truth"
        ),
    }


def _core_parts(geometry) -> list[float]:
    core = geometry.buffer(-(HALF_WIDTH_M - EROSION_TOLERANCE_M))
    if core.is_empty:
        return []
    parts = list(core.geoms) if core.geom_type == "MultiPolygon" else [core]
    return sorted((part.area for part in parts), reverse=True)


def _inset(comparison: pd.DataFrame, geometry_by_id: gpd.GeoSeries) -> dict[str, object]:
    row = comparison.set_index("unit_id").loc[LAYOUT_INSET_UNIT]
    parts = _core_parts(geometry_by_id.loc[LAYOUT_INSET_UNIT])
    return {
        "unit_id": LAYOUT_INSET_UNIT,
        "equivalent_rectangle_m": float(row["width_equivalent_rectangle_m"]),
        "area_perimeter_m": float(row["width_area_perimeter_m"]),
        "erosion_core_parts": len(parts),
        "erosion_core_parts_over_500_m2": sum(area > 500 for area in parts),
    }


def _overlap_history(screened: gpd.GeoDataFrame, prefix: str) -> dict[str, object]:
    """Compare the three materiality rules this project has used on one overlay."""

    raw_m2 = screened[f"{prefix}_overlap_m2"]
    pct = screened[f"{prefix}_overlap_pct"]
    material = screened[f"{prefix}_material"]
    area_only = raw_m2 > 1.0
    pct_only = area_only & (pct >= 1.0)
    # Large overlaps that the 1%-only rule reported as minor advisories; they
    # are now clip-required.
    missed_by_pct = area_only & (pct < 1.0) & (raw_m2 >= 10_000.0)
    # Overlaps that the 1%-only rule treated as material although no part of
    # them is 15 m wide.
    sliver_only = pct_only & (screened[f"{prefix}_overlap_core_m2"] <= 1.0)
    return {
        f"{prefix}_area_only_flags": int(area_only.sum()),
        f"{prefix}_pct_only_flags": int(pct_only.sum()),
        f"{prefix}_material_flags": int(material.sum()),
        f"{prefix}_ge_1ha_below_1pct_units": int(missed_by_pct.sum()),
        f"{prefix}_ge_1ha_below_1pct_overlap_ha": round(float(raw_m2[missed_by_pct].sum() / 10_000.0), 1),
        f"{prefix}_ge_1ha_below_1pct_max_overlap_ha": round(
            float(raw_m2[missed_by_pct].max() / 10_000.0) if missed_by_pct.any() else 0.0, 1
        ),
        f"{prefix}_sliver_only_units_previously_material": int(sliver_only.sum()),
        f"{prefix}_clip_required_units": int(screened[f"{prefix}_clip_required"].sum()),
        f"{prefix}_advisory_units": int((area_only & ~material).sum()),
    }


def main() -> None:
    candidates = gpd.read_file(DATA)
    comparison = pd.read_csv(OUTPUT / "width_method_comparison.csv")
    audit = pd.read_csv(OUTPUT / "rule_results.csv")
    screened = gpd.GeoDataFrame(
        pd.concat(
            [gpd.read_file(OUTPUT / "candidates.gpkg"), gpd.read_file(OUTPUT / "quarantine.gpkg")],
            ignore_index=True,
        ),
        geometry="geometry",
        crs=2193,
    )
    status_counts = screened["status"].value_counts()
    advisory_candidates = candidate_advisory_mask(screened)
    outcomes = audit.groupby(["rule_id", "outcome"]).size()
    candidate_flags = (
        screened.loc[advisory_candidates, "advisory_rule_ids"].str.split("|").explode().value_counts()
    )

    nztm_pass = candidates.geometry.area >= 10_000.0
    geographic = candidates.to_crs(4326)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        naive_wgs84_pass = (geographic.geometry.area / 10_000.0) >= 1.0
    unit_area_ha = candidates.geometry.area / 10_000.0

    # Width. R-02 needs an erosion core and an equivalent-rectangle width; the
    # earlier 2A/P comparison is kept so the change is traceable.
    ap_disagree = comparison["area_perimeter_pass"] != comparison["erosion_core_pass"]
    core_only = comparison["erosion_core_pass"] & ~comparison["equivalent_rectangle_pass"]
    geometry_by_id = screened.set_index("unit_id").geometry
    ap_disagree_geometries = geometry_by_id.loc[comparison.loc[ap_disagree, "unit_id"]]
    solidity = ap_disagree_geometries.area / ap_disagree_geometries.convex_hull.area
    core_only_ids = comparison.loc[core_only, "unit_id"]
    core_parts = geometry_by_id.loc[core_only_ids].map(_core_parts)
    split_cores = core_parts.map(len) >= 2
    lobes = {
        size: int(core_parts.map(lambda parts: sum(area > size for area in parts) >= 2).sum())
        for size in LOBE_SIZES_M2
    }

    findings = {
        "scope": SCOPE,
        "study_area": "Gisborne District",
        "input_lcdb_units": len(candidates),
        "lcdb_unit_area_ha_min": round(float(unit_area_ha.min()), 4),
        "lcdb_unit_area_ha_median": round(float(unit_area_ha.median()), 4),
        "lcdb_unit_area_ha_max": round(float(unit_area_ha.max()), 4),
        "candidate_review": int(status_counts.get("candidate_review", 0)),
        "candidate_review_clean": int(
            status_counts.get("candidate_review", 0) - advisory_candidates.sum()
        ),
        "candidate_review_with_advisory": int(advisory_candidates.sum()),
        "candidate_review_area_ha": round(
            float(screened.loc[screened["status"] == "candidate_review"].geometry.area.sum() / 10_000.0), 1
        ),
        "candidate_review_conflict_free_area_ha": round(
            float(screened.loc[screened["status"] == "candidate_review", "conflict_free_area_ha"].sum()), 1
        ),
        "candidate_advisory_flags": {
            flag: int(candidate_flags.get(flag, 0))
            for flag in (
                "R-01-near-threshold",
                "R-01-contiguous",
                "R-02-contiguous",
                "R-03-clip-required",
                "R-03-low-overlap",
                "R-04-clip-required",
                "R-04-low-overlap",
            )
        },
        "quarantine": int(status_counts.get("quarantine", 0)),
        "excluded": int(status_counts.get("excluded", 0)),
        "automated_reject_rate": round(
            float(1 - status_counts.get("candidate_review", 0) / len(candidates)), 4
        ),
        "failed_by_rule": {
            rule_id: int(outcomes.get((rule_id, "fail"), 0))
            for rule_id in ("R-01", "R-02", "R-03", "R-04", "R-05")
        },
        "ap_vs_erosion_disagreements": int(ap_disagree.sum()),
        "ap_vs_erosion_disagreement_rate": round(float(ap_disagree.mean()), 4),
        "ap_vs_erosion_disagreements_convex": int((solidity >= 0.99).sum()),
        "ap_vs_erosion_disagreement_median_area_ha": round(
            float(ap_disagree_geometries.area.median() / 10_000.0), 4
        ),
        "width_method_disagreements": int(comparison["methods_disagree"].sum()),
        "erosion_core_but_rectangle_below_threshold": int(core_only.sum()),
        "rectangle_pass_but_no_erosion_core": int(
            (comparison["equivalent_rectangle_pass"] & ~comparison["erosion_core_pass"]).sum()
        ),
        "core_only_units_with_split_core": int(split_cores.sum()),
        "core_only_units_with_two_parts_over_500_m2": lobes[500],
        "core_only_units_with_two_parts_over_1000_m2": lobes[1000],
        "width_example_ids": core_only_ids.astype(str).head(3).tolist(),
        "nztm_area_pass": int(nztm_pass.sum()),
        "naive_wgs84_area_pass": int(naive_wgs84_pass.sum()),
        "false_rejections_if_square_degrees_treated_as_square_metres": int(
            (nztm_pass & ~naive_wgs84_pass).sum()
        ),
        "false_qualifications_in_same_error": int((~nztm_pass & naive_wgs84_pass).sum()),
        **_overlap_history(screened, "pre1990"),
        **_overlap_history(screened, "conservation"),
        "layout_inset": _inset(comparison, geometry_by_id),
    }
    findings.update(_visual_review_findings(OUTPUT / "review"))
    (OUTPUT / "findings.json").write_text(
        json.dumps(findings, indent=2), encoding="utf-8", newline="\n"
    )
    # Nested values are written as JSON so the CSV cell can be parsed back.
    pd.DataFrame(
        [
            (key, json.dumps(value) if isinstance(value, (dict, list)) else value)
            for key, value in findings.items()
        ],
        columns=["finding", "value"],
    ).to_csv(OUTPUT / "findings.csv", index=False)

    examples = comparison[core_only].head(3).merge(
        candidates[["unit_id", "geometry"]], on="unit_id", how="left"
    )
    fig, axes = plt.subplots(1, 3, figsize=(12, 4), constrained_layout=True)
    for axis, (_, row) in zip(axes, examples.iterrows()):
        geometry = row.geometry
        core = geometry.buffer(-(HALF_WIDTH_M - EROSION_TOLERANCE_M))
        gpd.GeoSeries([geometry], crs=2193).boundary.plot(
            ax=axis, color="#164e63", linewidth=2
        )
        if not core.is_empty:
            gpd.GeoSeries([core], crs=2193).plot(
                ax=axis, color="#f59e0b", alpha=0.65, edgecolor="#b45309"
            )
        axis.set_title(
            f"{row.unit_id}\nrectangle width={row.width_equivalent_rectangle_m:.1f} m; "
            f"erosion={'pass' if row.erosion_core_pass else 'fail'}",
            fontsize=9,
        )
        axis.set_aspect("equal")
        axis.axis("off")
    for axis in axes[len(examples):]:
        axis.axis("off")
    fig.suptitle(
        "Real Gisborne width disagreements: -15 m erosion core in amber",
        fontsize=13,
        fontweight="bold",
    )
    fig.text(
        0.01, 0.005,
        "Screening / triage only - not an eligibility determination. "
        "Data: LCDB v6.0 (c) Manaaki Whenua, CC BY 4.0; modified.",
        fontsize=7, color="#555555",
    )
    fig.savefig(
        OUTPUT / "figures" / "width_disagreement_cases.png", dpi=180, metadata=PNG_METADATA
    )
    plt.close(fig)
    print(json.dumps(findings, indent=2))


if __name__ == "__main__":
    main()
