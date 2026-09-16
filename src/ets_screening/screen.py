"""Run rule-based post-1989 forest-land screening."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path

import geopandas as gpd
import pandas as pd

from .demo_data import build_demo_layers, write_demo_layers
from .geometry import compare_width_methods
from .io_utils import normalise_gpkg
from .load import read_layer
from .report import plot_layout_pdf, plot_screening_overview, plot_width_comparison
from .rules import RuleConfig, evaluate_rules
from .sample_review import write_review_bundle


class RejectRateExceeded(RuntimeError):
    """Raised when the batch looks more like a broken input than a normal run."""


def _summary(results: gpd.GeoDataFrame, comparison: pd.DataFrame) -> pd.DataFrame:
    total = len(results)
    counts = results["status"].value_counts()
    advisory_candidates = (
        (results["status"] == "candidate_review")
        & results["advisory_rule_ids"].fillna("").ne("")
    )
    return pd.DataFrame(
        [
            ("total_features", str(total)),
            ("candidate_review", str(int(counts.get("candidate_review", 0)))),
            (
                "candidate_review_clean",
                str(int(counts.get("candidate_review", 0) - advisory_candidates.sum())),
            ),
            ("candidate_review_with_advisory", str(int(advisory_candidates.sum()))),
            ("quarantine", str(int(counts.get("quarantine", 0)))),
            ("excluded", str(int(counts.get("excluded", 0)))),
            ("automated_reject_rate", f"{float((results['status'] != 'candidate_review').mean()):.4f}"),
            ("width_method_disagreements", str(int(comparison["methods_disagree"].sum()))),
            ("manual_rules_out_of_scope", "3"),
            ("crs_epsg", "2193"),
        ],
        columns=["metric", "value"],
    )


def _advisory_candidates(results: gpd.GeoDataFrame) -> pd.DataFrame:
    """List candidates carrying a non-material overlap flag, worst overlap first.

    These units passed screening but touch mapped pre-1990 or conservation
    polygons below the materiality thresholds. The summary count alone is not
    enough to act on, so they are also emitted as a sortable list: these are the
    cases where substituting an authoritative parcel or stand boundary is most
    likely to change the answer.
    """

    advisory = results[
        (results["status"] == "candidate_review")
        & results["advisory_rule_ids"].fillna("").ne("")
    ]
    listing = pd.DataFrame(
        {
            "unit_id": advisory["unit_id"],
            "lcdb_class": advisory["lcdb_class"],
            "area_ha": (advisory.geometry.area / 10_000.0).round(4),
            "advisory_rule_ids": advisory["advisory_rule_ids"],
            "pre1990_overlap_m2": advisory["pre1990_overlap_m2"],
            "pre1990_overlap_pct": advisory["pre1990_overlap_pct"],
            "conservation_overlap_m2": advisory["conservation_overlap_m2"],
            "conservation_overlap_pct": advisory["conservation_overlap_pct"],
        }
    )
    listing["max_overlap_pct"] = listing[
        ["pre1990_overlap_pct", "conservation_overlap_pct"]
    ].max(axis=1)
    return listing.sort_values(
        ["max_overlap_pct", "unit_id"], ascending=[False, True]
    ).reset_index(drop=True)


def run_screening(
    candidates: gpd.GeoDataFrame,
    pre1990: gpd.GeoDataFrame,
    conservation: gpd.GeoDataFrame,
    output_dir: str | Path,
    reject_rate_threshold: float = 0.80,
    config: RuleConfig | None = None,
    study_label: str = "User-supplied screening run",
    data_note: str = "Provided inputs",
    review_sample_ids: list[str] | None = None,
) -> dict[str, object]:
    results, audit = evaluate_rules(candidates, pre1990, conservation, config)
    comparison = compare_width_methods(results)
    reject_rate = float((results["status"] != "candidate_review").mean())
    if reject_rate > reject_rate_threshold:
        raise RejectRateExceeded(
            f"reject rate {reject_rate:.1%} exceeds {reject_rate_threshold:.1%}; "
            "publication aborted because the input may be wrong"
        )

    output_dir = Path(output_dir)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="ets-screen-", dir=output_dir.parent))
    try:
        candidates_out = results[results["status"] == "candidate_review"].copy()
        review_out = results[results["status"] != "candidate_review"].copy()
        candidates_out.to_file(stage / "candidates.gpkg", layer="candidates", driver="GPKG")
        review_out.to_file(stage / "quarantine.gpkg", layer="quarantine", driver="GPKG")
        normalise_gpkg(stage / "candidates.gpkg")
        normalise_gpkg(stage / "quarantine.gpkg")
        audit.to_csv(stage / "rule_results.csv", index=False)
        summary = _summary(results, comparison)
        summary.to_csv(stage / "summary.csv", index=False)
        comparison.to_csv(stage / "width_method_comparison.csv", index=False)
        _advisory_candidates(results).to_csv(
            stage / "advisory_candidates.csv", index=False
        )
        overview_path = stage / "figures" / "screening_overview.png"
        plot_screening_overview(
            results,
            conservation,
            pre1990,
            overview_path,
            title=study_label,
        )
        plot_width_comparison(comparison, stage / "figures" / "width_method_comparison.png")
        plot_layout_pdf(
            overview_path,
            results,
            comparison,
            stage / "layout_map.pdf",
            study_label,
            data_note,
        )
        write_review_bundle(
            candidates_out,
            stage / "review",
            sample_size=30,
            api_key=os.getenv("LINZ_BASEMAP_API_KEY"),
            sample_ids=review_sample_ids,
        )
        normalise_gpkg(stage / "review" / "review_queue.gpkg")
        manifest = {
            "scope": "screening/triage only; not an eligibility determination",
            "crs": "EPSG:2193",
            "input_feature_type": (
                "LCDB land-cover mapping units; not cadastral parcels or ETS application areas"
            ),
            "feature_count": len(results),
            "overlap_materiality": {
                "minimum_area_m2_exclusive": (config or RuleConfig()).minimum_overlap_area_m2,
                "minimum_source_unit_pct_inclusive": (config or RuleConfig()).minimum_overlap_pct,
                "status_below_both_thresholds": "advisory",
            },
            "reject_rate": reject_rate,
            "reject_rate_threshold": reject_rate_threshold,
            "unresolved_rules": ["R-03", "R-06", "R-07", "R-08"],
        }
        (stage / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        output_dir.mkdir(parents=True, exist_ok=True)
        managed_names = {
            "candidates.gpkg",
            "quarantine.gpkg",
            "summary.csv",
            "rule_results.csv",
            "width_method_comparison.csv",
            "advisory_candidates.csv",
            "run_manifest.json",
            "layout_map.pdf",
            "figures",
        }
        for child in (output_dir / name for name in managed_names):
            if not child.exists():
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        generated_review = stage / "review"
        output_review = output_dir / "review"
        output_review.mkdir(parents=True, exist_ok=True)
        for name in (
            "review_queue.gpkg",
            "review_sample_ids.csv",
            "review_labels_template.csv",
            "review_map.html",
        ):
            target = output_review / name
            if target.exists():
                target.unlink()
            shutil.copy2(generated_review / name, target)
        for child in stage.iterdir():
            if child.name == "review":
                continue
            os.replace(child, output_dir / child.name)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates")
    parser.add_argument("--pre1990")
    parser.add_argument("--conservation")
    parser.add_argument("--output", default="outputs")
    parser.add_argument("--reject-rate-threshold", type=float, default=0.80)
    parser.add_argument("--demo", action="store_true", help="Run deterministic synthetic NZTM fixtures")
    parser.add_argument("--study-label", default="User-supplied screening run")
    parser.add_argument("--data-note", default="Provided inputs")
    args = parser.parse_args()

    if args.demo:
        candidates, pre1990, conservation = build_demo_layers()
    else:
        missing = [name for name in ("candidates", "pre1990", "conservation") if not getattr(args, name)]
        if missing:
            parser.error(f"missing required inputs: {', '.join(missing)}")
        candidates = read_layer(args.candidates, ("unit_id", "lcdb_class"), "candidates")
        pre1990 = read_layer(args.pre1990, name="pre1990")
        conservation = read_layer(args.conservation, name="conservation")

    manifest = run_screening(
        candidates,
        pre1990,
        conservation,
        args.output,
        args.reject_rate_threshold,
        study_label=args.study_label,
        data_note=args.data_note,
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
