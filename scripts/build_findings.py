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

from ets_screening.review_labels import load_review_labels


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed" / "gisborne_candidates.gpkg"
OUTPUT = ROOT / "outputs" / "gisborne"


def _visual_review_findings(review_dir: Path) -> dict[str, object]:
    """Report the imagery review only when a named person has completed it.

    Until then the findings record the pending state rather than a rate, so no
    accuracy number in this repository can be read as the author's own imagery
    interpretation when it is not.
    """

    expected = pd.read_csv(review_dir / "review_sample_ids.csv", dtype=str)["unit_id"]
    labels_path = review_dir / "review_labels.csv"
    if not labels_path.exists():
        return {
            "visual_review_status": "pending_independent_human_review",
            "visual_review_sample_size": int(len(expected)),
            "visual_review_labels_recorded": 0,
        }
    labels = load_review_labels(labels_path, expected.tolist())
    counts = labels["review_label"].value_counts()
    plausible = int(counts.get("plausible-plantable", 0))
    return {
        "visual_review_status": "complete",
        "visual_review_sample_size": int(len(expected)),
        "visual_review_labels_recorded": int(len(labels)),
        "visual_plausible_plantable": plausible,
        "visual_already_forested": int(counts.get("already-forested", 0)),
        "visual_clearly_not_plantable": int(counts.get("clearly-not-plantable", 0)),
        "visual_agreement_rate": round(plausible / len(labels), 4),
        "visual_reviewer": "; ".join(sorted(set(labels["reviewer"]))),
        "visual_review_limitation": (
            "Single-reviewer interpretation of one imagery date; no ground truth"
        ),
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
    advisory_candidates = (
        (screened["status"] == "candidate_review")
        & screened["advisory_rule_ids"].fillna("").ne("")
    )
    failed_counts = audit[audit["passed"] == False].groupby("rule_id").size()  # noqa: E712

    nztm_pass = candidates.geometry.area >= 10_000.0
    geographic = candidates.to_crs(4326)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        naive_wgs84_pass = (geographic.geometry.area / 10_000.0) >= 1.0
    disagreements = comparison[comparison["methods_disagree"]]
    direction = disagreements.groupby(
        ["area_perimeter_pass", "erosion_core_pass"]
    ).size()
    unit_area_ha = candidates.geometry.area / 10_000.0
    legacy_r03 = screened["pre1990_overlap_m2"] > 1.0
    legacy_r04 = screened["conservation_overlap_m2"] > 1.0
    material_r03 = legacy_r03 & (screened["pre1990_overlap_pct"] >= 1.0)
    material_r04 = legacy_r04 & (screened["conservation_overlap_pct"] >= 1.0)
    low_r03 = legacy_r03 & ~material_r03
    low_r04 = legacy_r04 & ~material_r04

    findings = {
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
        "quarantine": int(status_counts.get("quarantine", 0)),
        "excluded": int(status_counts.get("excluded", 0)),
        "automated_reject_rate": round(
            float(1 - status_counts.get("candidate_review", 0) / len(candidates)), 4
        ),
        "failed_by_rule": {
            rule_id: int(failed_counts.get(rule_id, 0))
            for rule_id in ("R-01", "R-02", "R-03", "R-04", "R-05")
        },
        "width_method_disagreements": int(len(disagreements)),
        "width_disagreement_rate": round(float(len(disagreements) / len(candidates)), 4),
        "ap_fail_erosion_pass": int(direction.get((False, True), 0)),
        "ap_pass_erosion_fail": int(direction.get((True, False), 0)),
        "width_example_ids": disagreements["unit_id"].astype(str).head(3).tolist(),
        "nztm_area_pass": int(nztm_pass.sum()),
        "naive_wgs84_area_pass": int(naive_wgs84_pass.sum()),
        "false_rejections_if_square_degrees_treated_as_square_metres": int(
            (nztm_pass & ~naive_wgs84_pass).sum()
        ),
        "false_qualifications_in_same_error": int((~nztm_pass & naive_wgs84_pass).sum()),
        "legacy_r03_area_only_flags": int(legacy_r03.sum()),
        "material_r03_flags_at_1pct": int(material_r03.sum()),
        "r03_low_overlap_units_reclassified_to_advisory": int(low_r03.sum()),
        "legacy_r04_area_only_flags": int(legacy_r04.sum()),
        "material_r04_flags_at_1pct": int(material_r04.sum()),
        "r04_low_overlap_units_reclassified_to_advisory": int(low_r04.sum()),
        "r04_low_overlap_source_unit_area_ha": round(
            float(screened.loc[low_r04].geometry.area.sum() / 10_000.0), 1
        ),
        "r04_all_area_only_flagged_source_unit_area_ha": round(
            float(screened.loc[legacy_r04].geometry.area.sum() / 10_000.0), 1
        ),
        "r04_low_overlap_actual_intersection_area_ha": round(
            float(screened.loc[low_r04, "conservation_overlap_m2"].sum() / 10_000.0), 1
        ),
    }
    findings.update(_visual_review_findings(OUTPUT / "review"))
    (OUTPUT / "findings.json").write_text(json.dumps(findings, indent=2), encoding="utf-8")
    pd.DataFrame(findings.items(), columns=["finding", "value"]).to_csv(
        OUTPUT / "findings.csv", index=False
    )

    examples = disagreements.head(3).merge(
        candidates[["unit_id", "geometry"]], on="unit_id", how="left"
    )
    fig, axes = plt.subplots(1, 3, figsize=(12, 4), constrained_layout=True)
    for axis, (_, row) in zip(axes, examples.iterrows()):
        geometry = row.geometry
        core = geometry.buffer(-15)
        gpd.GeoSeries([geometry], crs=2193).boundary.plot(
            ax=axis, color="#164e63", linewidth=2
        )
        if not core.is_empty:
            gpd.GeoSeries([core], crs=2193).plot(
                ax=axis, color="#f59e0b", alpha=0.65, edgecolor="#b45309"
            )
        axis.set_title(
            f"{row.unit_id}\n2A/P={row.width_area_perimeter_m:.1f} m; erosion=pass",
            fontsize=9,
        )
        axis.set_aspect("equal")
        axis.axis("off")
    fig.suptitle(
        "Real Gisborne width disagreements: -15 m erosion core in amber",
        fontsize=13,
        fontweight="bold",
    )
    fig.savefig(OUTPUT / "figures" / "width_disagreement_cases.png", dpi=180)
    plt.close(fig)
    print(json.dumps(findings, indent=2))


if __name__ == "__main__":
    main()
