"""Input loading and fail-loud validation."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import geopandas as gpd

EXPECTED_EPSG = 2193


class InputValidationError(ValueError):
    """Raised when an input cannot support defensible metric screening."""


def assert_nztm2000(frame: gpd.GeoDataFrame, name: str = "input") -> None:
    """Require NZTM2000 so area and buffer distances are in metres.

    Reprojection is deliberately not automatic. A caller must make the CRS
    decision explicitly before entering the screening pipeline.
    """

    if frame.crs is None:
        raise InputValidationError(f"{name} has no CRS; expected EPSG:{EXPECTED_EPSG}")
    if frame.crs.to_epsg() != EXPECTED_EPSG:
        raise InputValidationError(
            f"{name} uses {frame.crs}; expected EPSG:{EXPECTED_EPSG} (NZTM2000). "
            "Metric area and width tests are unsafe in this CRS."
        )


def validate_geometry(frame: gpd.GeoDataFrame, name: str) -> None:
    if frame.empty:
        raise InputValidationError(f"{name} is empty")
    if frame.geometry.isna().any() or frame.geometry.is_empty.any():
        raise InputValidationError(f"{name} contains null or empty geometry")
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
    if frame["unit_id"].isna().any() or frame["unit_id"].duplicated().any():
        raise InputValidationError("unit_id must be present and unique")
    polygonal = frame.geometry.geom_type.eq("Polygon")
    if not polygonal.all():
        raise InputValidationError(
            "candidate geometries must be single-part Polygon features; explode multipart inputs first"
        )
    overlap_area = float(frame.geometry.area.sum() - frame.geometry.union_all().area)
    if overlap_area > 1e-6:
        raise InputValidationError(
            f"candidate polygons overlap by {overlap_area:.3f} m2; submitted mapping must not overlap"
        )


def read_layer(path: str | Path, required_columns: Iterable[str] = (), name: str = "layer") -> gpd.GeoDataFrame:
    frame = gpd.read_file(path)
    assert_nztm2000(frame, name)
    validate_geometry(frame, name)
    missing = set(required_columns) - set(frame.columns)
    if missing:
        raise InputValidationError(f"{name} is missing columns: {sorted(missing)}")
    return frame
