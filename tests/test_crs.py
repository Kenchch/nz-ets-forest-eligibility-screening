import geopandas as gpd
import pytest
from shapely.geometry import MultiPolygon, Polygon, box

from ets_screening.load import InputValidationError, assert_nztm2000, read_layer, validate_candidates


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


@pytest.mark.parametrize("unit_ids", [[1, "1"], ["", "B"], ["  ", "B"], [None, "B"]])
def test_ids_must_remain_present_and_unique_when_serialized(unit_ids):
    candidate = gpd.GeoDataFrame(
        {"unit_id": unit_ids, "lcdb_class": ["Low Producing Grassland"] * 2},
        geometry=[box(0, 0, 100, 100), box(200, 0, 300, 100)],
        crs=2193,
    )
    with pytest.raises(InputValidationError, match="unit_id"):
        validate_candidates(candidate)


@pytest.mark.parametrize("unit_id", [" A", "A ", "\tA", "A\n"])
def test_ids_cannot_change_when_review_files_trim_whitespace(unit_id):
    candidate = frame(2193)
    candidate.loc[0, "unit_id"] = unit_id
    with pytest.raises(InputValidationError, match="whitespace"):
        validate_candidates(candidate)


@pytest.mark.parametrize("geometry", [None, Polygon(), Polygon([(0, 0), (100, 100), (0, 100), (100, 0)])])
def test_null_empty_and_invalid_candidates_are_rejected(geometry):
    candidate = frame(2193)
    candidate.loc[0, "geometry"] = geometry
    with pytest.raises(InputValidationError, match="geometry"):
        validate_candidates(candidate)


def test_large_disjoint_batch_is_not_rejected_by_area_cancellation():
    # A sum-minus-union overlap check loses precision at this batch area.
    geometries = [
        box(
            1_000_000 + (i % 10) * 15_000,
            5_000_000 + (i // 10) * 15_000,
            1_000_000 + (i % 10) * 15_000 + 9999.7,
            5_000_000 + (i // 10) * 15_000 + 9999.7,
        )
        for i in range(100)
    ]
    candidate = gpd.GeoDataFrame(
        {"unit_id": [str(i) for i in range(100)], "lcdb_class": ["Low Producing Grassland"] * 100},
        geometry=geometries,
        crs=2193,
    )
    validate_candidates(candidate)


def test_boundary_touching_candidates_with_duplicate_row_indices_are_accepted():
    candidate = gpd.GeoDataFrame(
        {"unit_id": ["A", "B"], "lcdb_class": ["Low Producing Grassland"] * 2},
        geometry=[box(0, 0, 100, 100), box(100, 0, 200, 100)],
        index=[7, 7],
        crs=2193,
    )
    validate_candidates(candidate)


@pytest.mark.parametrize(
    "crs",
    [
        "EPSG:2193+7839",
        "+proj=tmerc +lat_0=0 +lon_0=173 +k=0.9996 +x_0=1600000 +y_0=10000000 "
        "+ellps=GRS80 +towgs84=0,0,0,0,0,0,0 +units=m +no_defs",
    ],
)
def test_equivalent_nztm_definitions_are_accepted(crs):
    frame = gpd.GeoDataFrame({"unit_id": ["a"]}, geometry=[box(0, 0, 1, 1)], crs=crs)
    assert_nztm2000(frame)


def test_transverse_mercator_on_another_meridian_is_rejected():
    crs = "+proj=tmerc +lat_0=0 +lon_0=174 +k=0.9996 +x_0=1600000 +y_0=10000000 +ellps=GRS80 +units=m"
    frame = gpd.GeoDataFrame({"unit_id": ["a"]}, geometry=[box(0, 0, 1, 1)], crs=crs)
    with pytest.raises(InputValidationError, match="EPSG:2193"):
        assert_nztm2000(frame)


def test_read_layer_accepts_compound_nztm_and_rejects_web_mercator(tmp_path):
    frame = gpd.GeoDataFrame(
        {"unit_id": ["a"], "lcdb_class": ["Low Producing Grassland"]},
        geometry=[box(1_600_000, 5_700_000, 1_600_100, 5_700_100)],
        crs="EPSG:2193+7839",
    )
    good = tmp_path / "compound.gpkg"
    frame.to_file(good, layer="units", driver="GPKG")
    assert len(read_layer(good, ("unit_id",), "candidates")) == 1
    bad = tmp_path / "mercator.gpkg"
    frame.set_crs(3857, allow_override=True).to_file(bad, layer="units", driver="GPKG")
    with pytest.raises(InputValidationError, match="EPSG:2193"):
        read_layer(bad, ("unit_id",), "candidates")


@pytest.mark.parametrize("missing", ["unit_id", "lcdb_class"])
def test_read_layer_names_missing_columns(tmp_path, missing):
    frame = gpd.GeoDataFrame(
        {"unit_id": ["a"], "lcdb_class": ["Low Producing Grassland"]},
        geometry=[box(0, 0, 100, 100)],
        crs=2193,
    ).drop(columns=missing)
    path = tmp_path / "layer.gpkg"
    frame.to_file(path, driver="GPKG")
    with pytest.raises(InputValidationError, match=missing):
        read_layer(path, ("unit_id", "lcdb_class"), "candidates")
