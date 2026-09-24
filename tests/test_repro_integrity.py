"""Verify that reproducibility checks cover the meaning of the evidence."""

from hashlib import sha256
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import Polygon, box

from scripts import semantic_hashes, verify_checksums


def _frame():
    return gpd.GeoDataFrame({"unit_id": ["a", "b"], "value": [1, 2]}, geometry=[box(0, 0, 1, 1), box(1, 1, 2, 2)], crs=2193)


def _hash(monkeypatch, frame, layers=("layer",)):
    monkeypatch.setattr(semantic_hashes, "_layers", lambda path: list(layers))
    monkeypatch.setattr(semantic_hashes.gpd, "read_file", lambda path, layer: frame)
    return semantic_hashes.semantic_hash(Path("ignored.gpkg"))


def test_semantic_hash_detects_crs_changes(monkeypatch):
    frame = _frame()
    assert _hash(monkeypatch, frame) != _hash(monkeypatch, frame.set_crs(3857, allow_override=True))


def test_semantic_hash_detects_renamed_fields(monkeypatch):
    frame = _frame()
    assert _hash(monkeypatch, frame) != _hash(monkeypatch, frame.rename(columns={"value": "wrong_meaning"}))


def test_semantic_hash_canonicalises_row_and_ring_order(monkeypatch):
    frame = _frame()
    equivalent = frame.iloc[::-1].copy()
    equivalent.geometry = equivalent.geometry.map(lambda geometry: Polygon(list(geometry.exterior.coords)[::-1]))
    assert _hash(monkeypatch, frame) == _hash(monkeypatch, equivalent)


def test_semantic_hash_detects_an_extra_layer(monkeypatch):
    frame = _frame()
    assert _hash(monkeypatch, frame) != _hash(monkeypatch, frame, layers=("layer", "zz_extra"))


def test_semantic_hash_detects_type_changes(monkeypatch):
    frame = _frame()
    assert _hash(monkeypatch, frame) != _hash(monkeypatch, frame.astype({"value": "float64"}))


def test_semantic_hash_tolerates_last_digit_float_noise(monkeypatch):
    frame = _frame().astype({"value": "float64"})
    noisy = frame.copy()
    noisy["value"] = noisy["value"] + 1e-12
    noisy.geometry = noisy.geometry.translate(1e-9, 0)
    assert _hash(monkeypatch, frame) == _hash(monkeypatch, noisy)


def test_semantic_hash_refuses_duplicate_unit_ids(monkeypatch):
    frame = _frame()
    frame["unit_id"] = "same"
    with pytest.raises(SystemExit, match="duplicate unit_id"):
        _hash(monkeypatch, frame)


def test_empty_layers_with_different_schema_have_different_hashes(monkeypatch):
    frame = _frame().iloc[:0]
    assert _hash(monkeypatch, frame) != _hash(monkeypatch, frame.rename(columns={"value": "wrong_meaning"}))


def _manifest(monkeypatch, tmp_path, text):
    data = tmp_path / "data"
    data.mkdir()
    (data / "checksums.sha256").write_text(text, encoding="utf-8")
    monkeypatch.setattr(verify_checksums, "ROOT", tmp_path)
    return data


def test_empty_checksum_manifest_does_not_report_success(monkeypatch, tmp_path):
    _manifest(monkeypatch, tmp_path, "# no inputs\n")
    with pytest.raises(SystemExit, match="no pinned inputs"):
        verify_checksums.main()


def test_checksum_manifest_rejects_paths_outside_data(monkeypatch, tmp_path):
    _manifest(monkeypatch, tmp_path, "0" * 64 + "  ../outside\n")
    with pytest.raises(SystemExit, match="outside the data directory"):
        verify_checksums.main()


def test_checksum_manifest_verifies_bytes_and_rejects_corruption(monkeypatch, tmp_path):
    expected = sha256(b"pinned input").hexdigest()
    data = _manifest(monkeypatch, tmp_path, expected + "  input.gpkg\n")
    source = data / "input.gpkg"
    source.write_bytes(b"pinned input")
    verify_checksums.main()
    source.write_bytes(b"changed input")
    with pytest.raises(SystemExit, match="checksum mismatch"):
        verify_checksums.main()


def test_reproduction_stops_before_outputs_change_if_review_pin_is_missing(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import reproduce
    from ets_screening.review_labels import ReviewLabelError

    monkeypatch.setattr(reproduce, "ROOT", tmp_path)
    monkeypatch.setattr(reproduce, "verify_checksums", lambda: None)

    def unexpected(*args, **kwargs):
        pytest.fail("screening must not start before the pinned review IDs are validated")

    monkeypatch.setattr(reproduce, "run_screening", unexpected)
    with pytest.raises(ReviewLabelError, match="cannot read review CSV"):
        reproduce.main()


def test_committed_review_cards_match_the_pinned_sample():
    from urllib.parse import unquote

    from ets_screening.review_labels import load_review_sample_ids

    review = Path(__file__).resolve().parents[1] / "outputs" / "gisborne" / "review"
    expected = sorted(load_review_sample_ids(review / "review_sample_ids.csv"))
    cards = sorted(path.name for path in (review / "cards").glob("[0-9][0-9]_*.jpg"))
    assert [unquote(name.split("_", 1)[1][: -len(".jpg")]) for name in cards] == expected
    assert [int(name[:2]) for name in cards] == list(range(1, len(expected) + 1))
