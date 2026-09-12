import geopandas as gpd
import pytest
from shapely.geometry import MultiPolygon, box

from ets_screening.load import InputValidationError, assert_nztm2000, validate_candidates


def frame(crs):
    return gpd.GeoDataFrame(
        {"unit_id": ["A"], "lcdb_class": ["Low Producing Grassland"], "geometry": [box(0, 0, 100, 100)]},
        crs=crs,
    )


def test_nztm_is_accepted():
    assert_nztm2000(frame(2193))


def test_wgs84_fails_loudly():
    with pytest.raises(InputValidationError, match="EPSG:2193"):
        assert_nztm2000(frame(4326))


def test_duplicate_ids_are_rejected():
    candidate = gpd.GeoDataFrame(
        {
            "unit_id": ["A", "A"],
            "lcdb_class": ["Low Producing Grassland"] * 2,
            "geometry": [box(0, 0, 100, 100), box(200, 0, 300, 100)],
        },
        crs=2193,
    )
    with pytest.raises(InputValidationError, match="unique"):
        validate_candidates(candidate)


def test_same_shape_in_wgs84_would_destroy_area_threshold():
    metric = frame(2193)
    geographic = metric.to_crs(4326)
    correct_area_m2 = metric.geometry.iloc[0].area
    naive_square_degrees = geographic.geometry.iloc[0].area
    assert correct_area_m2 == pytest.approx(10_000)
    assert naive_square_degrees < 1


def test_multipart_candidates_are_rejected():
    candidate = gpd.GeoDataFrame(
        {
            "unit_id": ["A"],
            "lcdb_class": ["Low Producing Grassland"],
            "geometry": [MultiPolygon([box(0, 0, 100, 100), box(200, 0, 300, 100)])],
        },
        crs=2193,
    )
    with pytest.raises(InputValidationError, match="single-part"):
        validate_candidates(candidate)


def test_overlapping_candidates_are_rejected():
    candidate = gpd.GeoDataFrame(
        {
            "unit_id": ["A", "B"],
            "lcdb_class": ["Low Producing Grassland"] * 2,
            "geometry": [box(0, 0, 100, 100), box(50, 0, 150, 100)],
        },
        crs=2193,
    )
    with pytest.raises(InputValidationError, match="overlap"):
        validate_candidates(candidate)
