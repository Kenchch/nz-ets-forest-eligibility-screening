"""Deterministic synthetic NZTM fixtures located near Gisborne.

The geometries are invented and must never be represented as real land units.
They exist so CI can exercise every branch without redistributing source data.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
from shapely.geometry import box
from shapely.ops import unary_union

from .io_utils import normalise_gpkg

CRS = "EPSG:2193"


def build_demo_layers() -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, gpd.GeoDataFrame]:
    x0, y0 = 2_050_000.0, 5_711_000.0
    dumbbell = unary_union(
        [
            box(x0 + 700, y0, x0 + 780, y0 + 80),
            box(x0 + 780, y0 + 35, x0 + 1_180, y0 + 45),
            box(x0 + 1_180, y0, x0 + 1_260, y0 + 80),
        ]
    )
    l_shape = unary_union(
        [
            box(x0 + 1_350, y0, x0 + 1_410, y0 + 220),
            box(x0 + 1_410, y0, x0 + 1_530, y0 + 60),
        ]
    )

    rows = [
        ("G01", "High Producing Exotic Grassland", box(x0, y0, x0 + 120, y0 + 100), "compact candidate"),
        ("G02", "Low Producing Grassland", box(x0, y0 + 180, x0 + 500, y0 + 200), "20 m strip"),
        ("G03", "High Producing Exotic Grassland", box(x0 + 560, y0, x0 + 640, y0 + 80), "below 1 ha"),
        ("G04", "Gorse and/or Broom", dumbbell, "dumbbell with 10 m neck"),
        ("G05", "Low Producing Grassland", box(x0, y0 + 300, x0 + 130, y0 + 400), "conservation overlap"),
        ("G06", "Exotic Forest", box(x0 + 200, y0 + 300, x0 + 320, y0 + 400), "LCDB proxy fails"),
        ("G07", "High Producing Exotic Grassland", box(x0 + 400, y0 + 300, x0 + 550, y0 + 400), "pre-1990 overlap"),
        ("G08", "Mixed Exotic Shrubland", l_shape, "irregular candidate"),
        ("G09", "Bare or Lightly Vegetated Surfaces", box(x0 + 1_600, y0, x0 + 1_700, y0 + 120), "proxy candidate"),
        ("G10", "Urban Parkland/Open Space", box(x0 + 1_800, y0, x0 + 1_910, y0 + 100), "urban proxy fails"),
        ("G11", "Low Producing Grassland", box(x0 + 650, y0 + 300, x0 + 950, y0 + 340), "40 m long rectangle"),
        ("G12", "High Producing Exotic Grassland", box(x0 + 1_050, y0 + 300, x0 + 1_150, y0 + 400), "compact boundary case"),
    ]
    candidates = gpd.GeoDataFrame(
        rows,
        columns=["unit_id", "lcdb_class", "geometry", "demo_case"],
        geometry="geometry",
        crs=CRS,
    )
    pre1990 = gpd.GeoDataFrame(
        {"source_id": ["P90-DEMO-01"], "geometry": [box(x0 + 430, y0 + 320, x0 + 520, y0 + 390)]},
        crs=CRS,
    )
    conservation = gpd.GeoDataFrame(
        {"source_id": ["PCL-DEMO-01"], "geometry": [box(x0 + 20, y0 + 320, x0 + 110, y0 + 390)]},
        crs=CRS,
    )
    return candidates, pre1990, conservation


def write_demo_layers(directory: str | Path) -> tuple[Path, Path, Path]:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    candidates, pre1990, conservation = build_demo_layers()
    paths = (
        directory / "demo_candidates.gpkg",
        directory / "demo_pre1990.gpkg",
        directory / "demo_conservation.gpkg",
    )
    for frame, path, layer in zip(
        (candidates, pre1990, conservation),
        paths,
        ("candidates", "pre1990", "conservation"),
    ):
        if path.exists():
            path.unlink()
        frame.to_file(path, layer=layer, driver="GPKG")
        normalise_gpkg(path)
    return paths


if __name__ == "__main__":
    for output in write_demo_layers("data/sample"):
        print(output)
