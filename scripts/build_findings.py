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


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed" / "gisborne_candidates.gpkg"
OUTPUT = ROOT / "outputs" / "gisborne"


def main() -> None:
    candidates = gpd.read_file(DATA)
    comparison = pd.read_csv(OUTPUT / "width_method_comparison.csv")
    labels = pd.read_csv(OUTPUT / "review" / "review_labels.csv")
    audit = pd.read_csv(OUTPUT / "rule_results.csv")
    status_counts = pd.concat(
        [gpd.read_file(OUTPUT / "candidates.gpkg"), gpd.read_file(OUTPUT / "quarantine.gpkg")]
    )["status"].value_counts()
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
    label_counts = labels["review_label"].value_counts()

    findings = {
        "study_area": "Gisborne District",
        "input_candidates": len(candidates),
        "candidate_review": int(status_counts.get("candidate_review", 0)),
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
        "width_example_ids": disagreements["parcel_id"].astype(str).head(3).tolist(),
        "nztm_area_pass": int(nztm_pass.sum()),
        "naive_wgs84_area_pass": int(naive_wgs84_pass.sum()),
        "false_rejections_if_square_degrees_treated_as_square_metres": int(
            (nztm_pass & ~naive_wgs84_pass).sum()
        ),
        "false_qualifications_in_same_error": int((~nztm_pass & naive_wgs84_pass).sum()),
        "visual_review_n": len(labels),
        "visual_plausible_plantable": int(label_counts.get("plausible-plantable", 0)),
        "visual_already_forested": int(label_counts.get("already-forested", 0)),
        "visual_clearly_not_plantable": int(label_counts.get("clearly-not-plantable", 0)),
        "visual_agreement_rate": round(
            float(label_counts.get("plausible-plantable", 0) / len(labels)), 4
        ),
        "visual_review_limitation": (
            "Single AI-assisted visual review of 2024 imagery; no independent ground truth."
        ),
    }
    (OUTPUT / "findings.json").write_text(json.dumps(findings, indent=2), encoding="utf-8")
    pd.DataFrame(findings.items(), columns=["finding", "value"]).to_csv(
        OUTPUT / "findings.csv", index=False
    )

    examples = disagreements.head(3).merge(
        candidates[["parcel_id", "geometry"]], on="parcel_id", how="left"
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
            f"{row.parcel_id}\n2A/P={row.width_area_perimeter_m:.1f} m; erosion=pass",
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
