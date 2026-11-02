import geopandas as gpd
import pytest
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from ets_screening.geometry import (
    compare_width_methods,
    width_area_perimeter,
    width_equivalent_rectangle,
    width_erosion,
)
from ets_screening.load import InputValidationError


def test_rectangle_width_proxies():
    wide = box(0, 0, 120, 100)
    strip = box(0, 0, 500, 20)
    assert width_area_perimeter(wide) == pytest.approx(54.545, rel=1e-3)
    assert width_erosion(wide)
    assert width_area_perimeter(strip) < 30
    assert not width_erosion(strip)


def test_dumbbell_exposes_proxy_disagreement():
    # Two 80 m blocks joined by a 400 m, 10 m wide neck: a 30 m core survives in
    # each block, but the average width is well under 30 m.
    dumbbell = unary_union(
        [box(0, 0, 80, 80), box(80, 35, 480, 45), box(480, 0, 560, 80)]
    )
    frame = gpd.GeoDataFrame({"unit_id": ["D1"], "geometry": [dumbbell]}, crs=2193)
    result = compare_width_methods(frame)
    assert bool(result.loc[0, "erosion_core_pass"])
    assert bool(result.loc[0, "methods_disagree"])


def test_empty_geometry_fails_both_proxies():
    empty = Polygon()
    assert not width_erosion(empty)
    assert width_area_perimeter(empty) != width_area_perimeter(empty)  # NaN


@pytest.mark.parametrize("value", [-15, 0, float("nan"), float("inf"), True])
def test_erosion_rejects_invalid_distances(value):
    with pytest.raises(ValueError, match="half_width_m"):
        width_erosion(box(0, 0, 100, 100), half_width_m=value)


@pytest.mark.parametrize("value", [-30, 0, float("nan"), float("inf"), True])
def test_width_comparison_rejects_invalid_thresholds(value):
    frame = gpd.GeoDataFrame({"unit_id": ["A"]}, geometry=[box(0, 0, 100, 100)], crs=2193)
    with pytest.raises(ValueError, match="threshold_m"):
        compare_width_methods(frame, threshold_m=value)


def test_width_comparison_requires_metric_nztm_crs():
    frame = gpd.GeoDataFrame({"unit_id": ["A"]}, geometry=[box(170, -42, 171, -41)], crs=4326)
    with pytest.raises(InputValidationError, match="EPSG:2193"):
        compare_width_methods(frame)


@pytest.mark.parametrize("width,length", [(20, 500), (30, 30), (33, 304), (45, 2000)])
def test_equivalent_rectangle_recovers_rectangle_width(width, length):
    assert width_equivalent_rectangle(box(0, 0, length, width)) == pytest.approx(width)


def test_equivalent_rectangle_of_compact_shape_is_equal_area_square_side():
    circle = box(0, 0, 1, 1).centroid.buffer(100)
    assert width_equivalent_rectangle(circle) == pytest.approx(circle.area ** 0.5)


def test_area_perimeter_under_reads_where_equivalent_rectangle_does_not():
    strip = box(0, 0, 304, 33)
    assert width_area_perimeter(strip) < 30 < width_equivalent_rectangle(strip)


def test_erosion_keeps_a_strip_of_exactly_the_threshold_width():
    assert width_erosion(box(0, 0, 500, 30))
    assert not width_erosion(box(0, 0, 500, 29.99))
