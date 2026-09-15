"""Cover the ArcGIS catalog-path translation without needing ArcGIS installed."""

import geopandas as gpd
import pytest
from shapely.geometry import Polygon

from ets_screening.arcgis_paths import split_dataset_path
from ets_screening.load import read_layer


def test_geopackage_catalog_path_is_split_and_schema_prefix_dropped():
    container, layer = split_dataset_path(r"C:\data\gisborne.gpkg\main.units")
    assert container.endswith("gisborne.gpkg")
    assert layer == "units"


def test_file_geodatabase_catalog_path_is_split():
    container, layer = split_dataset_path(r"C:\data\gisborne.gdb\units")
    assert container.endswith("gisborne.gdb")
    assert layer == "units"


def test_forward_slashes_are_handled():
    container, layer = split_dataset_path("C:/data/gisborne.gpkg/main.units")
    assert container.endswith("gisborne.gpkg")
    assert layer == "units"


@pytest.mark.parametrize(
    "path",
    [r"C:\data\gisborne.gpkg", r"C:\data\units.shp", r"C:\data\units.geojson"],
)
def test_plain_paths_are_returned_unchanged(path):
    container, layer = split_dataset_path(path)
    assert container == path
    assert layer is None


def test_a_layer_not_named_main_keeps_its_name():
    _, layer = split_dataset_path(r"C:\data\gisborne.gpkg\maintenance")
    assert layer == "maintenance"


def test_read_layer_opens_an_arcgis_style_geopackage_path(tmp_path):
    # The toolbox receives this exact shape of path from ArcGIS, and it used to
    # reach GDAL unchanged and fail with "No such file or directory".
    source = tmp_path / "study.gpkg"
    frame = gpd.GeoDataFrame(
        {"unit_id": ["a"], "lcdb_class": ["Low Producing Grassland"]},
        geometry=[Polygon([(0, 0), (0, 200), (200, 200), (200, 0)])],
        crs=2193,
    )
    frame.to_file(source, layer="candidates", driver="GPKG")

    loaded = read_layer(
        str(source / "main.candidates"), ("unit_id", "lcdb_class"), "candidates"
    )
    assert len(loaded) == 1
    assert loaded.crs.to_epsg() == 2193


def test_backslash_paths_split_on_every_platform():
    # pathlib resolves to PurePosixPath off Windows, where a backslash is an
    # ordinary character, so this used to return the path unsplit on Linux CI
    # while passing on the developer's Windows machine.
    container, layer = split_dataset_path(r"C:\data\gisborne.gpkg\main.units")
    assert (container, layer) == (r"C:\data\gisborne.gpkg", "units")


def test_container_keeps_the_separator_style_it_arrived_with():
    posix_container, _ = split_dataset_path("/srv/data/gisborne.gpkg/main.units")
    assert posix_container == "/srv/data/gisborne.gpkg"

    windows_container, _ = split_dataset_path(r"C:\data\gisborne.gpkg\main.units")
    assert windows_container == r"C:\data\gisborne.gpkg"


def test_a_suffix_inside_a_longer_name_is_not_a_boundary():
    path = r"C:\data\gisborne.gpkg.backup\units"
    container, layer = split_dataset_path(path)
    assert (container, layer) == (path, None)


def test_a_trailing_separator_leaves_no_layer():
    container, layer = split_dataset_path("C:/data/gisborne.gpkg/")
    assert (container, layer) == ("C:/data/gisborne.gpkg", None)


def test_the_deepest_container_wins():
    container, layer = split_dataset_path(r"C:\archive.gdb\gisborne.gpkg\main.units")
    assert (container, layer) == (r"C:\archive.gdb\gisborne.gpkg", "units")
