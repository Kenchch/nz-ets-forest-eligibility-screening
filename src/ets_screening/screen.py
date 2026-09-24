"""Run rule-based post-1989 forest-land screening."""

from __future__ import annotations

import argparse
from hashlib import sha256
import importlib.metadata
import json
import math
import platform
import shutil
import subprocess
import sys
import tempfile
import warnings
from pathlib import Path

import geopandas as gpd
import pandas as pd
from pyogrio.errors import DataSourceError

from .demo_data import build_demo_layers
from .io_utils import PublicationRecoveryError, normalise_gpkg, publish_outputs as _publish_outputs
from .load import InputValidationError, read_layer
from .report import plot_layout_pdf, plot_screening_overview, plot_width_comparison
from .review_labels import load_review_labels, load_review_sample_ids
from .rules import (
    RuleConfig,
    candidate_advisory_mask,
    evaluate_rules,
    manual_review_rule_ids,
    unmatched_plantable_classes,
)
from .sample_review import DEFAULT_REVIEW_SEED, DEFAULT_REVIEW_SIZE, write_review_bundle

SCOPE = "screening/triage only; not an eligibility determination"

#: Written into every output directory this tool owns. A non-empty directory
#: without it is refused, so a mistyped --output cannot overwrite someone's
#: files that happen to share a generated name.
OUTPUT_MARKER = ".ets_screening_output"

EXIT_INPUT_MISSING = 2
EXIT_INPUT_INVALID = 3
EXIT_REJECT_RATE = 4
EXIT_OUTPUT_REFUSED = 5


class RejectRateExceeded(RuntimeError):
    """Raised when the batch looks more like a broken input than a normal run."""


def _validate_preserved_review(output_dir: Path, generated_review: Path) -> None:
    """Do not pair a new sample with preserved labels or imagery for other IDs."""
    review = output_dir / "review"
    labels = review / "review_labels.csv"
    new_ids = load_review_sample_ids(generated_review / "review_sample_ids.csv")
    if labels.exists():
        load_review_labels(labels, new_ids)
    cards = review / "cards"
    if cards.exists() and any(cards.iterdir()):
        old_ids = load_review_sample_ids(review / "review_sample_ids.csv")
        if set(old_ids) != set(new_ids):
            raise ValueError(
                "review sample changed while imagery cards are present; "
                "use the pinned review_sample_ids or a separate output directory"
            )


def _check_output_directory(output_dir: Path) -> None:
    if output_dir.exists() and not output_dir.is_dir():
        raise FileExistsError(f"output path is not a directory: {output_dir}")
    if output_dir.exists() and any(output_dir.iterdir()) and not (output_dir / OUTPUT_MARKER).exists():
        raise FileExistsError(
            f"{output_dir} is not empty and was not created by ets-screen "
            f"(no {OUTPUT_MARKER}); choose an empty or new output directory"
        )


def _width_comparison(results: gpd.GeoDataFrame) -> pd.DataFrame:
    """Publish the widths the rules already measured instead of recomputing."""

    return pd.DataFrame(
        {
            "unit_id": results["unit_id"].astype(str).to_numpy(),
            "width_area_perimeter_m": results["width_ap_m"].to_numpy(),
            "area_perimeter_pass": results["width_ap_pass"].to_numpy(),
            "width_equivalent_rectangle_m": results["width_rect_m"].to_numpy(),
            "equivalent_rectangle_pass": results["width_rect_pass"].to_numpy(),
            "erosion_core_pass": results["width_core_pass"].to_numpy(),
            "methods_disagree": results["width_methods_disagree"].to_numpy(),
        }
    )


def _summary(results: gpd.GeoDataFrame, comparison: pd.DataFrame) -> pd.DataFrame:
    total = len(results)
    counts = results["status"].value_counts()
    advisory_candidates = candidate_advisory_mask(results)
    candidates = results["status"] == "candidate_review"
    candidate_area_ha = float(results.loc[candidates].geometry.area.sum() / 10_000.0)
    candidate_free_ha = float(results.loc[candidates, "conflict_free_area_ha"].sum())
    return pd.DataFrame(
        [
            ("total_features", str(total)),
            ("candidate_review", str(int(counts.get("candidate_review", 0)))),
            (
                "candidate_review_clean",
                str(int(counts.get("candidate_review", 0) - advisory_candidates.sum())),
            ),
            ("candidate_review_with_advisory", str(int(advisory_candidates.sum()))),
            ("candidate_review_area_ha", f"{candidate_area_ha:.1f}"),
            ("candidate_review_conflict_free_area_ha", f"{candidate_free_ha:.1f}"),
            ("quarantine", str(int(counts.get("quarantine", 0)))),
            ("excluded", str(int(counts.get("excluded", 0)))),
            ("automated_reject_rate", f"{float((results['status'] != 'candidate_review').mean()):.4f}"),
            ("width_method_disagreements", str(int(comparison["methods_disagree"].sum()))),
            ("rules_requiring_manual_review", str(len(manual_review_rule_ids()))),
            ("crs_epsg", "2193"),
            ("scope", SCOPE),
        ],
        columns=["metric", "value"],
    )


def _advisory_candidates(results: gpd.GeoDataFrame) -> pd.DataFrame:
    """List candidates carrying an advisory flag, worst overlap first.

    These units passed screening but only through a contiguity route, close to
    the area threshold, or while touching mapped pre-1990 or conservation
    polygons below the materiality thresholds. The summary count alone is not
    enough to act on, so they are also emitted as a sortable list.
    """

    advisory = results[candidate_advisory_mask(results)]
    listing = pd.DataFrame(
        {
            "unit_id": advisory["unit_id"],
            "lcdb_class": advisory["lcdb_class"],
            "area_ha": (advisory.geometry.area / 10_000.0).round(4),
            "conflict_free_area_ha": advisory["conflict_free_area_ha"],
            "contiguous_plantable_ha": advisory["contiguous_plantable_ha"],
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
        ["max_overlap_pct", "unit_id"], ascending=[False, True], kind="mergesort"
    ).reset_index(drop=True)


def _sampling_frame(candidates_out: gpd.GeoDataFrame) -> dict[str, object]:
    ids = sorted(candidates_out["unit_id"].astype(str))
    return {
        "sampling_frame_count": len(ids),
        "sampling_frame_sha256": sha256("\n".join(ids).encode("utf-8")).hexdigest(),
    }


def _run_environment() -> dict[str, object]:
    """Describe the machine and code version; varies by environment by design."""

    import pyogrio
    import pyproj
    import shapely

    packages = {}
    for name in ("nz-ets-forest-eligibility-screening", "geopandas", "shapely", "pyogrio",
                 "pyproj", "pandas", "numpy", "matplotlib", "pillow"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    environment: dict[str, object] = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "packages": packages,
        "gdal": pyogrio.__gdal_version_string__,
        "geos": shapely.geos_version_string,
        "proj": pyproj.proj_version_str,
        "git_commit": None,
        "git_dirty": None,
    }
    source = Path(__file__).resolve().parent
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=source, capture_output=True, text=True, check=True, timeout=10
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=source, capture_output=True, text=True, check=True, timeout=30
        ).stdout
        environment["git_commit"] = commit
        environment["git_dirty"] = bool(status.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return environment


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
    input_provenance: dict[str, object] | None = None,
) -> dict[str, object]:
    if not math.isfinite(reject_rate_threshold) or not 0 <= reject_rate_threshold <= 1:
        raise ValueError("reject_rate_threshold must be finite and between 0 and 1")
    config = config or RuleConfig()
    output_dir = Path(output_dir)
    _check_output_directory(output_dir)
    results, audit = evaluate_rules(candidates, pre1990, conservation, config)
    comparison = _width_comparison(results)
    reject_rate = float((results["status"] != "candidate_review").mean())
    if reject_rate > reject_rate_threshold:
        raise RejectRateExceeded(
            f"reject rate {reject_rate:.1%} exceeds {reject_rate_threshold:.1%}; "
            "publication aborted because the input may be wrong"
        )

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="ets-screen-", dir=output_dir.parent))
    retain_stage = False
    try:
        candidates_out = results[results["status"] == "candidate_review"].copy()
        review_out = results[results["status"] != "candidate_review"].copy()
        candidates_out.to_file(stage / "candidates.gpkg", layer="candidates", driver="GPKG")
        review_out.to_file(stage / "quarantine.gpkg", layer="quarantine", driver="GPKG")
        normalise_gpkg(stage / "candidates.gpkg")
        normalise_gpkg(stage / "quarantine.gpkg")
        audit.to_csv(stage / "rule_results.csv", index=False, lineterminator="\n")
        summary = _summary(results, comparison)
        summary.to_csv(stage / "summary.csv", index=False, lineterminator="\n")
        comparison.to_csv(stage / "width_method_comparison.csv", index=False, lineterminator="\n")
        _advisory_candidates(results).to_csv(
            stage / "advisory_candidates.csv", index=False, lineterminator="\n"
        )
        overview_path = stage / "figures" / "screening_overview.png"
        plot_screening_overview(
            results,
            conservation,
            pre1990,
            overview_path,
            title=study_label,
            data_note=data_note,
        )
        plot_width_comparison(
            comparison, stage / "figures" / "width_method_comparison.png",
            threshold_m=config.width_threshold_m,
            data_note=data_note,
        )
        plot_layout_pdf(
            overview_path,
            results,
            comparison,
            stage / "layout_map.pdf",
            study_label,
            data_note,
            width_threshold_m=config.width_threshold_m,
        )
        write_review_bundle(
            candidates_out,
            stage / "review",
            sample_size=DEFAULT_REVIEW_SIZE,
            sample_ids=review_sample_ids,
        )
        normalise_gpkg(stage / "review" / "review_queue.gpkg")
        _validate_preserved_review(output_dir, stage / "review")
        manual_ids = manual_review_rule_ids()
        manifest: dict[str, object] = {
            "scope": SCOPE,
            "crs": "EPSG:2193",
            "input_feature_type": (
                "LCDB land-cover mapping units; not cadastral parcels or ETS application areas"
            ),
            "feature_count": len(results),
            "rule_config": config.as_record(),
            "unmatched_plantable_lcdb_classes": unmatched_plantable_classes(candidates, config),
            "overlap_materiality": {
                "minimum_area_m2_exclusive": config.minimum_overlap_area_m2,
                "minimum_source_unit_pct_inclusive": config.minimum_overlap_pct,
                "clip_required_area_m2_inclusive": config.clip_required_overlap_m2,
                "sliver_width_removed_m": config.sliver_width_m,
                "status_when_not_material": "advisory (clip-required at or above the clip area)",
            },
            "reject_rate": reject_rate,
            "reject_rate_threshold": reject_rate_threshold,
            "unresolved_rules": manual_ids,
            "review_sample": {
                "size": DEFAULT_REVIEW_SIZE,
                "seed": DEFAULT_REVIEW_SEED,
                "pinned_ids_supplied": review_sample_ids is not None,
                **_sampling_frame(candidates_out),
            },
        }
        if input_provenance is not None:
            manifest["inputs"] = input_provenance
        (stage / "run_manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8", newline="\n"
        )
        # Kept apart from the manifest so the committed manifest stays
        # comparable across machines; this file is ignored by git.
        (stage / "run_environment.json").write_text(
            json.dumps(_run_environment(), indent=2), encoding="utf-8", newline="\n"
        )
        (stage / OUTPUT_MARKER).write_text(
            "Generated by ets-screen. Files with generated names in this directory "
            "are replaced on every run.\n",
            encoding="utf-8",
            newline="\n",
        )

        _publish_outputs(stage, output_dir)
    except PublicationRecoveryError:
        retain_stage = True
        raise
    finally:
        if not retain_stage:
            # Not ignore_errors=True: that silently swallowed every cleanup
            # failure, so a locked file left a staging directory behind in
            # outputs/ while the run still reported success.
            try:
                shutil.rmtree(stage)
            except OSError as error:
                warnings.warn(
                    f"could not remove staging directory {stage}: {error}",
                    RuntimeWarning,
                    stacklevel=2,
                )
    return manifest


def _fraction(text: str) -> float:
    try:
        value = float(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"not a number: {text!r}") from error
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise argparse.ArgumentTypeError("must be between 0 and 1")
    return value


def _package_version() -> str:
    try:
        return importlib.metadata.version("nz-ets-forest-eligibility-screening")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=(
            "Exit codes: 2 usage or missing input, 3 input validation failed, "
            "4 reject-rate gate tripped, 5 output directory refused."
        ),
    )
    parser.add_argument("--candidates", help="Candidate polygons (path, or path\\layer for a GeoPackage)")
    parser.add_argument("--pre1990", help="Mapped pre-1990 forest evidence polygons")
    parser.add_argument("--conservation", help="Public conservation land polygons")
    parser.add_argument("--output", default="outputs")
    parser.add_argument("--reject-rate-threshold", type=_fraction, default=0.80)
    parser.add_argument("--demo", action="store_true", help="Run deterministic synthetic NZTM fixtures")
    parser.add_argument("--study-label", default="User-supplied screening run")
    parser.add_argument("--data-note", default="Provided inputs")
    parser.add_argument("--version", action="version", version=f"%(prog)s {_package_version()}")
    args = parser.parse_args(argv)

    inputs = ("candidates", "pre1990", "conservation")
    try:
        if args.demo:
            supplied = [name for name in inputs if getattr(args, name)]
            if supplied:
                parser.error(f"--demo cannot be combined with --{', --'.join(supplied)}")
            candidates, pre1990, conservation = build_demo_layers()
        else:
            missing = [name for name in inputs if not getattr(args, name)]
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
    except InputValidationError as error:
        parser.exit(EXIT_INPUT_INVALID, f"{parser.prog}: input validation failed: {error}\n")
    except RejectRateExceeded as error:
        parser.exit(EXIT_REJECT_RATE, f"{parser.prog}: {error}\n")
    except FileExistsError as error:
        parser.exit(EXIT_OUTPUT_REFUSED, f"{parser.prog}: {error}\n")
    except (FileNotFoundError, DataSourceError) as error:
        # pyogrio reports an unreadable or missing dataset as DataSourceError,
        # not FileNotFoundError.
        parser.exit(EXIT_INPUT_MISSING, f"{parser.prog}: cannot read input: {error}\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main(sys.argv[1:])
