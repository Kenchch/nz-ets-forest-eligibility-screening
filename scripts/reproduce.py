"""Rebuild committed Gisborne screening outputs from pinned processed inputs."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

import geopandas as gpd

from ets_screening.review_labels import load_review_labels, load_review_sample_ids
from ets_screening.screen import run_screening
from build_findings import main as build_findings
from ingest_review_labels import main as ingest_review_labels
from verify_checksums import main as verify_checksums


ROOT = Path(__file__).resolve().parents[1]
INPUTS = {
    "candidates": "gisborne_candidates.gpkg",
    "pre1990": "gisborne_pre1990_evidence.gpkg",
    "conservation": "gisborne_conservation.gpkg",
}
DATA_NOTE = (
    "LCDB v6.0 (c) Manaaki Whenua - Landcare Research, CC BY 4.0; "
    "LUCAS LUM 2020 v005 (c) Ministry for the Environment, CC BY 4.0; "
    "Public Conservation Land (c) Crown / DOC, CC BY 4.0; "
    "Territorial Authority 2026 (c) Stats NZ, CC BY 4.0. Modified."
)


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    # Called from tests and other scripts with no argv: never read sys.argv here.
    parser.parse_args([] if argv is None else argv)

    verify_checksums()
    review_dir = ROOT / "outputs" / "gisborne" / "review"
    # Validate the pinned sample and existing human labels before replacing any
    # evidence. A missing pin must not silently select a different review set.
    review_sample_ids = load_review_sample_ids(review_dir / "review_sample_ids.csv")
    labels_path = review_dir / "review_labels.csv"
    if labels_path.exists():
        load_review_labels(labels_path, review_sample_ids)
    data = ROOT / "data" / "processed"
    frames = {name: gpd.read_file(data / filename) for name, filename in INPUTS.items()}
    source_manifest = json.loads((data / "gisborne_manifest.json").read_text(encoding="utf-8"))
    provenance = {
        "files": {filename: _sha256(data / filename) for filename in INPUTS.values()},
        "sources": source_manifest.get("sources", {}),
        "lcdb_geometry_note": source_manifest.get("lcdb_geometry_note"),
    }
    # The review sample is pinned by its own ID list, so reruns keep labelling
    # the same 30 polygons whether or not the human review has been completed.
    manifest = run_screening(
        frames["candidates"],
        frames["pre1990"],
        frames["conservation"],
        ROOT / "outputs" / "gisborne",
        reject_rate_threshold=0.80,
        study_label="Gisborne District open-data screening",
        data_note=DATA_NOTE,
        review_sample_ids=review_sample_ids,
        input_provenance=provenance,
    )
    build_findings()
    if ingest_review_labels([]) != 0:
        raise SystemExit("review labels rejected; see the message above")
    # arcgis/layout_map_arcgispro.pdf is deliberately not refreshed here. It is
    # exported from ArcGIS Pro by arcgis/build_layout.py; copying the Matplotlib
    # PDF over it would silently replace the cartographic output on every run.
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main(sys.argv[1:])
