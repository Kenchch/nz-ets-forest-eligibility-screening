"""Input loading and fail-loud validation."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import math
import warnings

import geopandas as gpd
from pyproj import CRS

from .arcgis_paths import split_dataset_path

EXPECTED_EPSG = 2193
#: NZTM2000 as projection parameters. A definition that matches these exactly
#: is NZTM whatever its authority code; loose EPSG matching is not used because
#: it maps a transverse Mercator on the wrong meridian to 2193 as well.
_NZTM_PARAMETERS = {
    "proj": "tmerc",
    "lat_0": 0.0,
    "lon_0": 173.0,
    "k": 0.9996,
    "x_0": 1_600_000.0,
    "y_0": 10_000_000.0,
    "ellps": "GRS80",
    "units": "m",
}


def _horizontal(crs: CRS) -> CRS:
    # EPSG:2193+7839 (NZTM + NZVD2016 heights) is still NZTM in plan.
    return crs.sub_crs_list[0] if crs.is_compound else crs


def is_nztm2000(crs: CRS | None) -> bool:
    if crs is None:
        return False
    horizontal = _horizontal(CRS(crs))
    if horizontal.to_epsg() == EXPECTED_EPSG:
        return True
    with warnings.catch_warnings():
        # to_dict() warns that PROJ strings are lossy; only these keys are compared.
        warnings.simplefilter("ignore", UserWarning)
        parameters = horizontal.to_dict()
    for key, expected in _NZTM_PARAMETERS.items():
        actual = parameters.get(key)
        if isinstance(expected, float):
            if not isinstance(actual, (int, float)) or not math.isclose(actual, expected, rel_tol=0, abs_tol=1e-9):
                return False
        elif actual != expected:
            return False
    return True


class InputValidationError(ValueError):
    """Raised when an input cannot support defensible metric screening."""


def assert_nztm2000(frame: gpd.GeoDataFrame, name: str = "input") -> None:
    """Require NZTM2000 so area and buffer distances are in metres.

    Reprojection is deliberately not automatic. A caller must make the CRS
    decision explicitly before entering the screening pipeline.
    """

    if frame.crs is None:
        raise InputValidationError(f"{name} has no CRS; expected EPSG:{EXPECTED_EPSG}")
    if not is_nztm2000(frame.crs):
        raise InputValidationError(
            f"{name} uses {frame.crs}; expected EPSG:{EXPECTED_EPSG} (NZTM2000). "
            "Metric area and width tests are unsafe in this CRS."
        )


def validate_geometry(frame: gpd.GeoDataFrame, name: str) -> None:
    if frame.empty:
        raise InputValidationError(f"{name} is empty")
    if frame.geometry.isna().any() or frame.geometry.is_empty.any():
        raise InputValidationError(f"{name} contains null or empty geometry")
    if not frame.geometry.geom_type.isin(["Polygon", "MultiPolygon"]).all():
        raise InputValidationError(f"{name} must contain only Polygon or MultiPolygon geometry")
    invalid = ~frame.geometry.is_valid
    if invalid.any():
        rows = list(frame.index[invalid][:5])
        raise InputValidationError(f"{name} contains invalid geometry at rows {rows}")


def validate_candidates(frame: gpd.GeoDataFrame) -> None:
    assert_nztm2000(frame, "candidates")
    validate_geometry(frame, "candidates")
    required = {"unit_id", "lcdb_class"}
    missing = required - set(frame.columns)
    if missing:
        raise InputValidationError(f"candidates is missing columns: {sorted(missing)}")
    # IDs are serialized as strings in comparison tables and review CSVs.
    # Check that representation too: integer 1 and text "1" must not collide.
    ids = frame["unit_id"].astype(str)
    if (
        frame["unit_id"].isna().any()
        or frame["unit_id"].duplicated().any()
        or ids.str.strip().eq("").any()
        or ids.duplicated().any()
    ):
        raise InputValidationError("unit_id must be present, non-blank and unique as text")
    if ids.ne(ids.str.strip()).any():
        raise InputValidationError("unit_id must not contain leading or trailing whitespace")
    polygonal = frame.geometry.geom_type.eq("Polygon")
    if not polygonal.all():
        raise InputValidationError(
            "candidate geometries must be single-part Polygon features; explode multipart inputs first"
        )
    # Subtracting two large batch areas can report overlap from rounding alone.
    # Measure each polygon against earlier intersecting polygons instead, with
    # local unions so triple intersections are not counted more than necessary.
    spatial_index = frame.sindex
    overlap_area = 0.0
    for position, geometry in enumerate(frame.geometry):
        neighbours = spatial_index.query(geometry, predicate="intersects")
        previous = neighbours[neighbours < position]
        if len(previous) == 0:
            continue
        target = frame.geometry.iloc[previous].union_all()
        overlap_area += float(geometry.intersection(target).area)
        if overlap_area > 1e-6:
            raise InputValidationError(
                f"candidate polygons overlap by at least {overlap_area:.6f} m2; "
                "submitted mapping must not overlap"
            )


def read_layer(path: str | Path, required_columns: Iterable[str] = (), name: str = "layer") -> gpd.GeoDataFrame:
    # An ArcGIS toolbox hands over a catalog path such as
    # "gisborne.gpkg\main.units", which GDAL cannot open directly.
    container, layer = split_dataset_path(path)
    frame = gpd.read_file(container) if layer is None else gpd.read_file(container, layer=layer)
    assert_nztm2000(frame, name)
    validate_geometry(frame, name)
    missing = set(required_columns) - set(frame.columns)
    if missing:
        raise InputValidationError(f"{name} is missing columns: {sorted(missing)}")
    return frame
