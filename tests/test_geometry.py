import geopandas as gpd
import pytest
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from ets_screening.geometry import compare_width_methods, width_area_perimeter, width_erosion


def test_rectangle_width_proxies():
    wide = box(0, 0, 120, 100)
    strip = box(0, 0, 500, 20)
    assert width_area_perimeter(wide) == pytest.approx(54.545, rel=1e-3)
    assert width_erosion(wide)
    assert width_area_perimeter(strip) < 30
    assert not width_erosion(strip)


def test_dumbbell_exposes_proxy_disagreement():
    dumbbell = unary_union(
        [box(0, 0, 80, 80), box(80, 30, 480, 50), box(480, 0, 560, 80)]
    )
    frame = gpd.GeoDataFrame({"unit_id": ["D1"], "geometry": [dumbbell]}, crs=2193)
    result = compare_width_methods(frame)
    assert bool(result.loc[0, "erosion_core_pass"])
    assert bool(result.loc[0, "methods_disagree"])


def test_empty_geometry_fails_both_proxies():
    empty = Polygon()
    assert not width_erosion(empty)
    assert width_area_perimeter(empty) != width_area_perimeter(empty)  # NaN
