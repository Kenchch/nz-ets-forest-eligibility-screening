"""Rebuild committed Gisborne screening outputs from pinned processed inputs."""

from pathlib import Path
import shutil

import geopandas as gpd
import pandas as pd

from ets_screening.screen import run_screening
from build_findings import main as build_findings
from ingest_review_labels import main as ingest_review_labels


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    data = ROOT / "data" / "processed"
    candidates = gpd.read_file(data / "gisborne_candidates.gpkg")
    pre1990 = gpd.read_file(data / "gisborne_pre1990_evidence.gpkg")
    conservation = gpd.read_file(data / "gisborne_conservation.gpkg")
    # The review sample is pinned by its own ID list, so reruns keep labelling
    # the same 30 polygons whether or not the human review has been completed.
    pinned_path = ROOT / "outputs" / "gisborne" / "review" / "review_sample_ids.csv"
    review_sample_ids = None
    if pinned_path.exists():
        review_sample_ids = pd.read_csv(pinned_path, dtype=str)["unit_id"].tolist()
    manifest = run_screening(
        candidates,
        pre1990,
        conservation,
        ROOT / "outputs" / "gisborne",
        reject_rate_threshold=0.80,
        study_label="Gisborne District open-data screening",
        data_note="LCDB v6 / LUCAS v005 / DOC PCL",
        review_sample_ids=review_sample_ids,
    )
    build_findings()
    if ingest_review_labels() != 0:
        raise SystemExit("review labels rejected; see the message above")
    shutil.copy2(
        ROOT / "outputs" / "gisborne" / "layout_map.pdf",
        ROOT / "arcgis" / "layout_map.pdf",
    )
    print(manifest)


if __name__ == "__main__":
    main()
