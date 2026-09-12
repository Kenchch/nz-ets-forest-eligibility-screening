"""Rebuild committed Gisborne screening outputs from pinned processed inputs."""

from pathlib import Path
import shutil

import geopandas as gpd
import pandas as pd

from ets_screening.screen import run_screening
from build_findings import main as build_findings


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    data = ROOT / "data" / "processed"
    candidates = gpd.read_file(data / "gisborne_candidates.gpkg")
    pre1990 = gpd.read_file(data / "gisborne_pre1990_evidence.gpkg")
    conservation = gpd.read_file(data / "gisborne_conservation.gpkg")
    labels_path = ROOT / "outputs" / "gisborne" / "review" / "review_labels.csv"
    review_sample_ids = None
    if labels_path.exists():
        labels = pd.read_csv(labels_path)
        id_column = "unit_id" if "unit_id" in labels.columns else "parcel_id"
        review_sample_ids = labels[id_column].astype(str).tolist()
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
    shutil.copy2(
        ROOT / "outputs" / "gisborne" / "layout_map.pdf",
        ROOT / "arcgis" / "layout_map.pdf",
    )
    print(manifest)


if __name__ == "__main__":
    main()
