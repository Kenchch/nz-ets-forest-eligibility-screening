"""Regressions for review artifacts crossing CSV, browser and SQLite boundaries."""

from html.parser import HTMLParser
import json
from pathlib import Path
import runpy
import shutil
import sqlite3
import subprocess

import geopandas as gpd
import pandas as pd
import pytest

from ets_screening.demo_data import build_demo_layers
from ets_screening.io_utils import normalise_gpkg
from ets_screening.review_labels import ReviewLabelError
from ets_screening.sample_review import select_review_sample, write_review_bundle


class _Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts = []
        self.in_script = False

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.scripts.append("")
            self.in_script = True

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_script = False

    def handle_data(self, data):
        if self.in_script:
            self.scripts[-1] += data


def test_map_treats_untrusted_properties_as_data(tmp_path):
    candidates, _, _ = build_demo_layers()
    candidates = candidates.head(1).copy()
    payload = '</script><script>alert("injected")</script><img src=x onerror=alert(1)>'
    candidates["unit_id"] = payload
    candidates["status"] = payload
    write_review_bundle(candidates, tmp_path)
    html = (tmp_path / "review_map.html").read_text(encoding="utf-8")
    scripts = _Scripts()
    scripts.feed(html)
    # Leaflet plus the authored map script; no input can create a third one.
    assert len(scripts.scripts) == 2
    map_script = scripts.scripts[1]
    encoded = map_script.split("const features=", 1)[1].split(";\nconst map=", 1)[0]
    properties = json.loads(encoded)["features"][0]["properties"]
    assert properties["unit_id"] == properties["status"] == payload
    assert "title.textContent=String(f.properties.unit_id)" in map_script
    assert "line.textContent=label+': '+String(f.properties[name])" in map_script
    assert "innerHTML" not in map_script
    assert "Content-Security-Policy" in html
    assert "default-src 'none'" in html


def test_map_publishes_only_review_fields(tmp_path):
    candidates, _, _ = build_demo_layers()
    candidates["applicant_note"] = "private applicant text"
    write_review_bundle(candidates, tmp_path, sample_size=3)
    html = (tmp_path / "review_map.html").read_text(encoding="utf-8")
    assert "private applicant text" not in html
    assert "applicant_note" not in html
    assert "triage only" in html
    assert "not an ETS eligibility determination" in html


def test_map_does_not_publish_build_machine_secrets(tmp_path, monkeypatch):
    candidates, _, _ = build_demo_layers()
    monkeypatch.setenv("LINZ_BASEMAP_API_KEY", "environment-secret")
    with pytest.warns(UserWarning, match="no longer embedded"):
        write_review_bundle(candidates, tmp_path, api_key="explicit-secret")
    for path in tmp_path.iterdir():
        assert b"environment-secret" not in path.read_bytes()
        assert b"explicit-secret" not in path.read_bytes()
    html = (tmp_path / "review_map.html").read_text(encoding="utf-8")
    assert "encodeURIComponent(key)" in html
    assert "requires an internet connection" in html


def test_empty_review_bundle_is_valid(tmp_path):
    candidates, _, _ = build_demo_layers()
    write_review_bundle(candidates.iloc[:0], tmp_path)
    assert gpd.read_file(tmp_path / "review_queue.gpkg").empty
    assert pd.read_csv(tmp_path / "review_sample_ids.csv").empty
    html = (tmp_path / "review_map.html").read_text(encoding="utf-8")
    assert "getBounds().isValid()" in html
    assert "No candidate polygons" in html


@pytest.mark.parametrize("sample_size", [-1, 1.5, True])
def test_invalid_sample_sizes_do_not_publish(tmp_path, sample_size):
    candidates, _, _ = build_demo_layers()
    with pytest.raises(ValueError, match="sample_size"):
        write_review_bundle(candidates, tmp_path, sample_size=sample_size)
    assert not list(tmp_path.iterdir())


def test_duplicate_candidate_ids_cannot_duplicate_review_rows():
    candidates, _, _ = build_demo_layers()
    candidates.loc[1, "unit_id"] = candidates.loc[0, "unit_id"]
    with pytest.raises(ReviewLabelError, match="duplicate unit_id"):
        select_review_sample(candidates)


def test_duplicate_pinned_ids_cannot_duplicate_review_rows():
    candidates, _, _ = build_demo_layers()
    with pytest.raises(ReviewLabelError, match="duplicate unit_id"):
        select_review_sample(candidates, sample_ids=["G01", "G01"])


def test_review_bundle_is_byte_stable_under_input_reordering(tmp_path):
    candidates, _, _ = build_demo_layers()
    first, second = tmp_path / "first", tmp_path / "second"
    write_review_bundle(candidates, first, sample_size=5)
    write_review_bundle(candidates.sample(frac=1, random_state=7), second, sample_size=5)
    for artifact in first.iterdir():
        assert artifact.read_bytes() == (second / artifact.name).read_bytes()


def test_failed_bundle_generation_preserves_previous_queue(tmp_path, monkeypatch):
    candidates, _, _ = build_demo_layers()
    write_review_bundle(candidates, tmp_path, sample_size=2)
    previous = {path.name: path.read_bytes() for path in tmp_path.iterdir()}

    def failed_write(self, filename, *args, **kwargs):
        Path(filename).write_bytes(b"partial database")
        raise OSError("disk full")

    monkeypatch.setattr(gpd.GeoDataFrame, "to_file", failed_write)
    with pytest.raises(OSError, match="disk full"):
        write_review_bundle(candidates, tmp_path, sample_size=5)
    assert previous == {path.name: path.read_bytes() for path in tmp_path.iterdir()}


def test_normalise_missing_gpkg_does_not_create_empty_database(tmp_path):
    path = tmp_path / "missing.gpkg"
    with pytest.raises(sqlite3.OperationalError):
        normalise_gpkg(path)
    assert not path.exists()


def test_normalise_wal_geopackage_preserves_integrity(tmp_path):
    candidates, _, _ = build_demo_layers()
    path = tmp_path / "queue.gpkg"
    candidates.to_file(path, driver="GPKG", layer="review_queue")
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.close()
    normalise_gpkg(path)
    connection = sqlite3.connect(path)
    try:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    finally:
        connection.close()
    assert gpd.read_file(path)["unit_id"].tolist() == candidates["unit_id"].tolist()


def test_failed_label_rewrite_preserves_original_evidence(tmp_path, monkeypatch):
    ingest = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts" / "ingest_review_labels.py"))
    path = tmp_path / "review_labels.csv"
    path.write_text("previous evidence", encoding="utf-8")

    def failed_csv(self, handle, *args, **kwargs):
        handle.write("partial replacement")
        raise OSError("disk full")

    monkeypatch.setattr(pd.DataFrame, "to_csv", failed_csv)
    with pytest.raises(OSError, match="disk full"):
        ingest["_write_csv"](pd.DataFrame({"unit_id": ["a"]}), path)
    assert path.read_text(encoding="utf-8") == "previous evidence"
    assert list(tmp_path.iterdir()) == [path]


def test_standalone_review_refresh_rolls_back_failed_publication(tmp_path, monkeypatch):
    from ets_screening import io_utils

    candidates, _, _ = build_demo_layers()
    write_review_bundle(candidates, tmp_path, sample_size=2)
    previous = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    original_replace = io_utils.os.replace
    failed = False

    def fail_once(source, target):
        nonlocal failed
        if Path(source).name == "review_queue.gpkg" and Path(target).parent == tmp_path and not failed:
            failed = True
            raise OSError("publication blocked")
        return original_replace(source, target)

    monkeypatch.setattr(io_utils.os, "replace", fail_once)
    with pytest.raises(OSError, match="publication blocked"):
        write_review_bundle(candidates, tmp_path, sample_size=5)
    assert previous == {path.name: path.read_bytes() for path in tmp_path.iterdir()}


def test_standalone_review_cannot_rebind_existing_imagery(tmp_path):
    candidates, _, _ = build_demo_layers()
    write_review_bundle(candidates, tmp_path, sample_size=2)
    previous = (tmp_path / "review_sample_ids.csv").read_bytes()
    cards = tmp_path / "cards"
    cards.mkdir()
    (cards / "review.jpg").write_bytes(b"existing imagery")
    with pytest.raises(ValueError, match="sample changed while imagery cards are present"):
        write_review_bundle(candidates, tmp_path, sample_size=3)
    assert (tmp_path / "review_sample_ids.csv").read_bytes() == previous


@pytest.mark.skipif(shutil.which("node") is None, reason="optional Node runtime for map JavaScript smoke test")
def test_generated_map_javascript_executes_and_loads_imagery_only_on_submit(tmp_path):
    candidates, _, _ = build_demo_layers()
    candidates = candidates.head(1).copy()
    candidates["unit_id"] = "<img src=x onerror=alert(1)>"
    candidates["status"] = "</script><script>alert(1)</script>"
    write_review_bundle(candidates, tmp_path)
    scripts = _Scripts()
    scripts.feed((tmp_path / "review_map.html").read_text(encoding="utf-8"))
    # Exercise the generated script against the small Leaflet/DOM surface it
    # uses. This catches runtime errors such as calling addTo on the onAdd
    # function, as well as unintended tile requests before the user submits.
    harness = r"""
const assert = require('node:assert/strict');
const vm = require('node:vm');
const source = require('node:fs').readFileSync(0, 'utf8');
const controls = [], popups = [], tiles = [];
const element = tag => ({tag, children: [], events: {}, textContent: '',
 append(...children) {this.children.push(...children);},
 addEventListener(name, callback) {this.events[name] = callback;}});
const map = {fitBounds() {}, setView() {}, removeLayer() {}};
const bounds = {isValid: () => true, pad() {return this;}};
const L = {
 map: () => map,
 geoJSON(features, options) {
  for (const feature of features.features) options.onEachFeature(feature, {bindPopup: p => popups.push(p)});
  return {addTo() {return this;}, getBounds: () => bounds};
 },
 control: Object.assign(() => ({addTo() {controls.push(this.onAdd()); return this;}}), {scale: () => ({addTo() {}})}),
 DomUtil: {create: element},
 DomEvent: {disableClickPropagation() {}, disableScrollPropagation() {}},
 tileLayer(url, options) {tiles.push({url, options}); return {addTo() {return this;}};}
};
vm.runInNewContext(source, {L, document: {createElement: element}});
assert.equal(popups[0].children[0].textContent, '<img src=x onerror=alert(1)>');
assert.equal(popups[0].children.at(-1).textContent, 'Status: </script><script>alert(1)</script>');
assert.equal(tiles.length, 0);
const form = controls.find(control => control.tag === 'form');
assert.ok(form);
const input = form.children.find(child => child.tag === 'label').children[0];
input.value = "key&next=https://attacker.invalid/'";
form.events.submit({preventDefault() {}});
assert.equal(tiles.length, 1);
const url = new URL(tiles[0].url);
assert.equal(url.origin, 'https://basemaps.linz.govt.nz');
assert.equal(url.searchParams.get('api'), "key&next=https://attacker.invalid/'");
assert.equal(url.searchParams.size, 1);
assert.equal(input.value, '');
"""
    result = subprocess.run(
        [shutil.which("node"), "-e", harness], input=scripts.scripts[1],
        text=True, encoding="utf-8", capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr
