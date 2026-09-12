"""Geometry diagnostics for the 30 metre average-width criterion.

Neither function is the legal MPI average-width measurement. The official
guidance uses perpendicular measurements at 20 metre intervals along a
centre line following the longest path. These functions are transparent
triage proxies that identify shapes needing assessor review.
"""

from __future__ import annotations

import math

import geopandas as gpd
import pandas as pd
from shapely.geometry.base import BaseGeometry


def width_area_perimeter(geometry: BaseGeometry) -> float:
    """Return 2A/P in metres as a compactness-sensitive width proxy."""

    if geometry is None or geometry.is_empty or geometry.length <= 0:
        return math.nan
    return 2.0 * geometry.area / geometry.length


def width_erosion(geometry: BaseGeometry, half_width_m: float = 15.0) -> bool:
    """Return whether any interior remains after a negative half-width buffer.

    A surviving core proves that the geometry is at least 30 m wide somewhere;
    it does not prove that its legally measured average width is at least 30 m.
    """

    if geometry is None or geometry.is_empty:
        return False
    return not geometry.buffer(-half_width_m).is_empty


def compare_width_methods(frame: gpd.GeoDataFrame, threshold_m: float = 30.0) -> pd.DataFrame:
    """Return per-feature results and disagreements for two screening proxies."""

    result = pd.DataFrame({"parcel_id": frame["parcel_id"].astype(str)})
    raw_width = frame.geometry.map(width_area_perimeter)
    result["width_area_perimeter_m"] = raw_width.round(3)
    result["area_perimeter_pass"] = raw_width >= threshold_m
    result["erosion_core_pass"] = frame.geometry.map(
        lambda geometry: width_erosion(geometry, threshold_m / 2.0)
    )
    result["methods_disagree"] = result["area_perimeter_pass"] != result["erosion_core_pass"]
    return result
