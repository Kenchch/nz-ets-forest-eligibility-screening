"""Offline checks for complete downloads and correctly registered review cards."""

import geopandas as gpd
from PIL import Image
import pytest
from shapely.geometry import Point, Polygon, box, mapping

from scripts import download_gisborne_data as download
from scripts import download_review_cards as cards


def _features(ids, **extra):
    return {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {"OID": value}, "geometry": mapping(box(value, 0, value + 1, 1))}
            for value in ids
        ],
        **extra,
    }


@pytest.mark.parametrize("explicit_limit", [False, True])
def test_download_recovers_every_id_when_service_truncates_batches(monkeypatch, explicit_limit):
    requests = []

    def request(url, params, **kwargs):
        if params.get("returnIdsOnly"):
            return {"objectIds": [3, 1, 2], "objectIdFieldName": "OID"}
        ids = list(map(int, params["objectIds"].split(",")))
        requests.append(ids)
        assert "OID" in params["outFields"].split(",")
        return _features(ids[:1], exceededTransferLimit=explicit_limit and len(ids) > 1)

    monkeypatch.setattr(download, "_request_json", request)
    result = download._download_by_bbox("service", (0, 0, 10, 10), "name")
    assert result["OID"].tolist() == [1, 2, 3]
    assert requests[0] == [1, 2, 3]


def test_download_fails_when_an_object_disappears_instead_of_caching_partial_data(monkeypatch):
    def request(url, params, **kwargs):
        if params.get("returnIdsOnly"):
            return {"objectIds": [1, 2], "objectIdFieldName": "OID"}
        return _features([1] if "1" in params["objectIds"].split(",") else [])

    monkeypatch.setattr(download, "_request_json", request)
    with pytest.raises(RuntimeError, match="requested object ID 2"):
        download._download_by_bbox("service", (0, 0, 10, 10), "OID")


@pytest.mark.parametrize("payload", [{}, {"objectIds": [1, 1]}, {"objectIds": ["1"]}])
def test_download_rejects_malformed_id_responses(monkeypatch, payload):
    monkeypatch.setattr(download, "_request_json", lambda *args, **kwargs: payload)
    with pytest.raises(RuntimeError, match="object ID"):
        download._download_by_bbox("service", (0, 0, 10, 10), "OID")


def test_download_rejects_duplicate_features_even_when_batch_count_matches(monkeypatch):
    def request(url, params, **kwargs):
        if params.get("returnIdsOnly"):
            return {"objectIds": [1, 2], "objectIdFieldName": "OID"}
        return _features([1, 1])

    monkeypatch.setattr(download, "_request_json", request)
    with pytest.raises(RuntimeError, match="duplicate ArcGIS features"):
        download._download_by_bbox("service", (0, 0, 10, 10), "OID")


@pytest.mark.parametrize("size", [0, -1, True, 1.5])
def test_download_rejects_invalid_batch_sizes(size):
    with pytest.raises(ValueError, match="positive integer"):
        download._download_by_bbox("service", (0, 0, 10, 10), "OID", batch_size=size)


def test_empty_geojson_response_has_an_usable_geometry_column(monkeypatch):
    monkeypatch.setattr(download, "_request_json", lambda *args, **kwargs: _features([]))
    result = download._query_geojson("service", {})
    assert result.empty
    assert result.geometry.name == "geometry"
    assert result.crs.to_epsg() == 2193


def test_clip_repairs_invalid_boundary():
    boundary = gpd.GeoDataFrame(geometry=[Polygon([(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)])], crs=2193)
    source = gpd.GeoDataFrame({"id": [1]}, geometry=[box(-1, -1, 3, 3)], crs=2193)
    result = download._clip(source, boundary)
    assert result.geometry.is_valid.all()
    assert result.geometry.area.sum() == pytest.approx(2)


def _world_point(pixel_x, pixel_y, level=10):
    resolution = cards.RESOLUTIONS[level]
    return Point(cards.ORIGIN_X + pixel_x * resolution, cards.ORIGIN_Y - pixel_y * resolution)


def test_detail_crosshair_is_registered_to_the_interior_point(monkeypatch):
    centre = _world_point(1535.25, 1280.25)
    geometry = centre.buffer(100)
    monkeypatch.setattr(cards, "_tile", lambda *args: Image.new("RGB", (256, 256), "white"))
    panel = cards._panel(geometry, 10, centre, mark_centre=True)
    assert panel.getpixel((384, 384)) == (255, 255, 0)
    # The boundary must be centred on the crosshair rather than the tile centre.
    radius = int(100 / cards.RESOLUTIONS[10])
    assert panel.getpixel((384 + radius, 384)) == (255, 45, 85)


def test_overview_centres_the_full_bounds_not_an_off_centre_interior_point(monkeypatch):
    shape = Polygon([(0, 0), (600, 0), (600, 50), (50, 50), (50, 600), (0, 600)])
    row = gpd.GeoDataFrame({"unit_id": ["a"], "lcdb_class": ["grass"]}, geometry=[shape], crs=2193).iloc[0]
    centres = []

    def panel(geometry, level, centre, **kwargs):
        centres.append(centre)
        return Image.new("RGB", (768, 768))

    monkeypatch.setattr(cards, "_panel", panel)
    cards._draw_card(row)
    assert centres[0].equals(Point(300, 300))
    assert centres[1].equals(shape.representative_point())


def test_card_outlines_polygon_holes(monkeypatch):
    centre = _world_point(1400, 1400)
    resolution = cards.RESOLUTIONS[10]
    outer = centre.buffer(200 * resolution, cap_style="square")
    inner = centre.buffer(100 * resolution, cap_style="square")
    geometry = Polygon(outer.exterior.coords, [inner.exterior.coords])
    monkeypatch.setattr(cards, "_tile", lambda *args: Image.new("RGB", (256, 256), "white"))
    panel = cards._panel(geometry, 10, centre)
    assert panel.getpixel((484, 384)) == (255, 45, 85)


@pytest.mark.parametrize("unit_id", ["a/../../outside", r"a\..\..\outside", "C:\\outside", 'a:*?"<>|'])
def test_card_identifiers_cannot_escape_the_destination(tmp_path, unit_id):
    path = cards._card_path(tmp_path, 1, unit_id)
    assert path.parent == tmp_path
    assert not any(character in path.name for character in '<>:"/\\|?*')


def test_card_filename_keeps_normal_pinned_ids_readable(tmp_path):
    assert cards._card_path(tmp_path, 1, "123-part-2").name == "01_123-part-2.jpg"


def test_part_numbers_follow_geometry_not_row_order():
    parts = gpd.GeoDataFrame(
        {"LCDB_UID": ["lcdb1", "lcdb1", "lcdb1", "lcdb2"]},
        geometry=[box(0, 0, 50, 50), box(100, 0, 400, 300), box(500, 0, 600, 100), box(0, 900, 10, 910)],
        crs=2193,
    )

    def mapping_of(frame):
        named = download._assign_unit_ids(frame)
        return {row.unit_id: round(row.geometry.area) for row in named.itertuples()}

    expected = mapping_of(parts)
    assert expected == {"lcdb1-part-1": 90000, "lcdb1-part-2": 10000, "lcdb1-part-3": 2500, "lcdb2": 100}
    for seed in range(5):
        assert mapping_of(parts.sample(frac=1, random_state=seed)) == expected


def test_transient_server_errors_are_retried(monkeypatch):
    import io
    import urllib.error

    calls = []

    class Response(io.BytesIO):
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def urlopen(request, timeout):
        calls.append(request)
        if len(calls) < 3:
            raise urllib.error.HTTPError("url", 503, "busy", {}, None)
        return Response(b'{"ok": true}')

    monkeypatch.setattr(download.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(download.time, "sleep", lambda seconds: None)
    assert download._request_json("https://example.invalid/query", {}) == {"ok": True}
    assert len(calls) == 3


def test_client_errors_are_not_retried(monkeypatch):
    import urllib.error

    calls = []

    def urlopen(request, timeout):
        calls.append(request)
        raise urllib.error.HTTPError("url", 400, "bad request", {}, None)

    monkeypatch.setattr(download.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(download.time, "sleep", lambda seconds: None)
    with pytest.raises(urllib.error.HTTPError):
        download._request_json("https://example.invalid/query", {})
    assert len(calls) == 1


def test_cache_is_reused_only_for_the_same_query(monkeypatch, tmp_path):
    monkeypatch.setattr(download, "RAW", tmp_path)
    downloads = []

    def fake_download(service, bbox, fields, *, batch_size, where):
        downloads.append(where)
        return gpd.GeoDataFrame({"OID": [1]}, geometry=[box(0, 0, 1, 1)], crs=2193)

    monkeypatch.setattr(download, "_download_by_bbox", fake_download)
    monkeypatch.setattr(download, "_service_info", lambda service: {"max_record_count": 200})
    download._cached_download("layer", "service", (0, 0, 1, 1), "OID", where="a")
    download._cached_download("layer", "service", (0, 0, 1, 1), "OID", where="a")
    assert downloads == ["a"]
    _, record = download._cached_download("layer", "service", (0, 0, 1, 1), "OID", where="b")
    assert downloads == ["a", "b"]
    assert record["query"]["where"] == "b"
    assert record["feature_count"] == 1


@pytest.mark.parametrize("limit,expected", [(200, 200), (2000, 500), (None, 500), (0, 500)])
def test_batch_size_respects_the_service_record_limit(limit, expected):
    assert download._batch_size({"max_record_count": limit}) == expected


def test_small_unit_overview_is_wider_than_the_detail_panel(monkeypatch):
    shape = box(0, 0, 80, 80)
    row = gpd.GeoDataFrame({"unit_id": ["a"], "lcdb_class": ["grass"]}, geometry=[shape], crs=2193).iloc[0]
    levels = []

    def panel(geometry, level, centre, **kwargs):
        levels.append(level)
        return Image.new("RGB", (768, 768))

    monkeypatch.setattr(cards, "_panel", panel)
    cards._draw_card(row)
    overview, detail = levels
    assert detail - overview >= cards.OVERVIEW_LEVELS_BELOW_DETAIL
