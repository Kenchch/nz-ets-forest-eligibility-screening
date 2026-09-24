"""Geometry diagnostics for the 30 metre average-width criterion.

None of these functions is the legal MPI average-width measurement. The
official guidance uses perpendicular measurements at 20 metre intervals along
a centre line following the longest path. These functions are transparent
triage proxies that identify shapes needing assessor review.
"""

from __future__ import annotations

import math
from numbers import Real

import geopandas as gpd
import pandas as pd
from shapely.geometry.base import BaseGeometry

from .load import assert_nztm2000, validate_geometry

#: The statute excludes land narrower than 30 m, not land exactly 30 m wide.
#: Eroding by exactly half the threshold leaves nothing of a 30.000 m strip,
#: which moved the effective threshold to about 30.0015 m. Eroding 1 mm less
#: keeps a sliver of core for a strip of exactly the threshold width.
EROSION_TOLERANCE_M = 1e-3


def _validate_width(value: float, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a finite number greater than zero")


def width_area_perimeter(geometry: BaseGeometry) -> float:
    """Return 2A/P in metres as a compactness-sensitive width proxy.

    For a W x L rectangle this is WL/(W+L), which is always below W and is only
    half of W for a square. It is kept as a diagnostic, not used by R-02.
    """

    if geometry is None or geometry.is_empty or geometry.length <= 0:
        return math.nan
    return 2.0 * geometry.area / geometry.length


def width_equivalent_rectangle(geometry: BaseGeometry) -> float:
    """Return the width of the rectangle with the same area and perimeter.

    Solving A = WL and P = 2(W + L) for the shorter side gives
    W = P/4 - sqrt((P/4)^2 - A). It is exact for rectangles of any length and
    reads low for ragged or branching outlines, whose perimeter is inflated.
    Shapes more compact than a square have no real solution and return
    sqrt(A), the side of the equal-area square.
    """

    if geometry is None or geometry.is_empty or geometry.length <= 0:
        return math.nan
    area = geometry.area
    quarter_perimeter = geometry.length / 4.0
    discriminant = quarter_perimeter**2 - area
    if discriminant <= 0:
        return math.sqrt(area)
    return quarter_perimeter - math.sqrt(discriminant)


def width_erosion(geometry: BaseGeometry, half_width_m: float = 15.0) -> bool:
    """Return whether any interior remains after a negative half-width buffer.

    A surviving core proves that the geometry is at least twice `half_width_m`
    wide somewhere; it does not prove that its legally measured average width
    is. The buffer is reduced by EROSION_TOLERANCE_M so a shape of exactly the
    threshold width passes.
    """

    _validate_width(half_width_m, "half_width_m")
    if geometry is None or geometry.is_empty:
        return False
    return not geometry.buffer(-(half_width_m - EROSION_TOLERANCE_M)).is_empty


def compare_width_methods(frame: gpd.GeoDataFrame, threshold_m: float = 30.0) -> pd.DataFrame:
    """Return per-feature width proxies and where the two R-02 proxies disagree.

    R-02 needs both an erosion core and an equivalent-rectangle width at the
    threshold. 2A/P is reported alongside for comparison with earlier runs.
    """

    _validate_width(threshold_m, "threshold_m")
    assert_nztm2000(frame, "width comparison")
    if not frame.empty:
        validate_geometry(frame, "width comparison")
    result = pd.DataFrame({"unit_id": frame["unit_id"].astype(str)})
    raw_ap = frame.geometry.map(width_area_perimeter)
    raw_rectangle = frame.geometry.map(width_equivalent_rectangle)
    result["width_area_perimeter_m"] = raw_ap.round(3)
    result["area_perimeter_pass"] = raw_ap >= threshold_m
    result["width_equivalent_rectangle_m"] = raw_rectangle.round(3)
    # The square root can land a few ULPs under an exact rectangle width.
    result["equivalent_rectangle_pass"] = raw_rectangle >= threshold_m - EROSION_TOLERANCE_M
    result["erosion_core_pass"] = frame.geometry.map(
        lambda geometry: width_erosion(geometry, threshold_m / 2.0)
    )
    result["methods_disagree"] = result["equivalent_rectangle_pass"] != result["erosion_core_pass"]
    return result
