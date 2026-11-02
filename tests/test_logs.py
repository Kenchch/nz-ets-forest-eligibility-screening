"""What each step leaves in the logs, and that nothing is configured on import."""

import json
import logging
from pathlib import Path
import re
import subprocess
import sys
import warnings

import geopandas as gpd
import pandas as pd
import pytest
from PIL import Image
from shapely.geometry import box

import download_gisborne_data as download
import download_review_cards as cards
import ingest_review_labels as ingest
from ets_screening import logs, screen
from ets_screening.demo_data import build_demo_layers
from ets_screening.screen import RejectRateExceeded, run_screening

# Not logs.ROOT: CI tests the installed package, whose files are not in the repository.
ROOT = Path(__file__).resolve().parents[1]


def messages(caplog, level=logging.INFO):
    return [r.getMessage() for r in caplog.records if r.levelno >= level]


def read(path):
    return path.read_text(encoding="utf-8")


@pytest.fixture
def info(caplog):
    caplog.set_level(logging.INFO, logger="ets_screening")
    return caplog


# ------------------------------------------------------------------ logs


def test_log_times_are_utc():
    record = logging.LogRecord("ets_screening", logging.INFO, __file__, 1, "x", None, None)
    record.created = 0.0  # 1970-01-01 00:00:00 UTC
    assert logs.FORMAT.format(record).startswith("1970-01-01T00:00:00Z  INFO     x")


def test_paths_in_logs_are_relative_to_the_repository():
    assert logs.rel(logs.ROOT / "outputs" / "gisborne") == "outputs/gisborne"
    outside = logs.ROOT.parent / "elsewhere" / "x"
    assert logs.rel(outside) == str(outside)


def test_console_is_added_once():
    logs.console()
    logs.console()
    assert sum(isinstance(h, logs._Console) for h in logs.log.handlers) == 1


def test_importing_the_package_and_scripts_configures_nothing():
    code = (
        "import logging, sys, warnings\n"
        f"sys.path.insert(0, {str(ROOT / 'scripts')!r})\n"
        "import ets_screening.screen, ets_screening.sample_review\n"
        "import reproduce, download_gisborne_data, download_review_cards\n"
        "package = logging.getLogger('ets_screening')\n"
        "assert package.handlers == [] and package.level == logging.NOTSET\n"
        "assert logging.getLogger().handlers == []\n"
        "assert logging.getLogger('py.warnings').handlers == []\n"
        "assert warnings.showwarning.__module__ == 'warnings'\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_a_step_logs_its_start_end_and_time(info):
    with logs.step("rules"):
        pass
    with pytest.raises(ZeroDivisionError):
        with logs.step("width comparison"):
            1 / 0
    got = messages(info)
    assert got[0] == "rules: start" and re.fullmatch(r"rules: done in \d+\.\d s", got[1])
    assert got[2] == "width comparison: start"
    assert re.fullmatch(
        r"width comparison: failed after \d+\.\d s: ZeroDivisionError: division by zero", got[3]
    )


def test_a_command_that_exits_logs_how_it_ended(tmp_path):
    path = tmp_path / "ets_screening.log"
    with pytest.raises(SystemExit):
        with logs.command("ingest_review_labels", path):
            raise SystemExit(0)
    with pytest.raises(SystemExit):
        with logs.command("ingest_review_labels", path):
            raise SystemExit(1)
    with pytest.raises(SystemExit):
        with logs.command("reproduce", path):
            raise SystemExit("review labels rejected; see the message above")
    text = read(path)
    assert "INFO     ingest_review_labels: done in" in text
    assert re.search(r"ERROR    ingest_review_labels: stopped after \d+\.\d s: exit status 1", text)
    assert re.search(
        r"ERROR    reproduce: stopped after \d+\.\d s: review labels rejected; "
        "see the message above",
        text,
    )


# ------------------------------------------------------------------ screening


def test_screening_logs_units_rule_moves_statuses_and_reject_rate(tmp_path, info):
    candidates, pre1990, conservation = build_demo_layers()
    run_screening(candidates, pre1990, conservation, tmp_path, 0.90)
    got = messages(info)

    assert (
        "screen: 12 units in; overlaying 1 pre-1990 evidence and 1 conservation polygons" in got
    )
    # Every count in the log is the count in the run's own tables.
    audit = pd.read_csv(tmp_path / "rule_results.csv")
    fails = audit[audit["passed"].astype(str) == "False"].groupby("rule_id").size()
    for rule_id in screen.AUTOMATED_RULE_IDS:
        line = next(m for m in got if m.startswith(f"{rule_id} "))
        assert f": {int(fails.get(rule_id, 0)):,} units fail (" in line
        assert line.split(" -> ")[1].startswith("excluded" if rule_id == "R-04" else "quarantine")
    summary = dict(pd.read_csv(tmp_path / "summary.csv", dtype=str).itertuples(index=False))
    assert (
        f"status: {summary['candidate_review']} candidate_review "
        f"({summary['candidate_review_clean']} clean, "
        f"{summary['candidate_review_with_advisory']} with an advisory flag), "
        f"{summary['quarantine']} quarantine, {summary['excluded']} excluded"
    ) in got
    rate = float(summary["automated_reject_rate"])
    assert (
        f"reject rate {rate:.2%} (quarantine and excluded), within the 90.00% threshold" in got
    )
    for name in ("rules", "width comparison", "write outputs", "publish"):
        assert any(re.fullmatch(rf"{name}: done in \d+\.\d s", m) for m in got), name


def test_the_reject_rate_gate_logs_the_rate_against_its_threshold(tmp_path, info):
    candidates, pre1990, conservation = build_demo_layers()
    with pytest.raises(RejectRateExceeded):
        run_screening(candidates, pre1990, conservation, tmp_path, 0.10)
    errors = messages(info, logging.ERROR)
    assert len(errors) == 1
    assert re.fullmatch(
        r"reject rate \d+\.\d\d% is above the 10\.00% threshold; nothing is published", errors[0]
    )
    assert not any(m.startswith("write outputs") for m in messages(info))


def test_ets_screen_appends_its_run_log_beside_the_outputs(tmp_path, monkeypatch, capsys):
    out = tmp_path / "out"
    argv = ["ets-screen", "--demo", "--output", str(out), "--reject-rate-threshold", "0.9"]
    monkeypatch.setattr(sys, "argv", argv)
    original = screen.plot_width_comparison

    def warn_then_plot(*args, **kwargs):
        warnings.warn("Tight layout not applied", UserWarning)  # as matplotlib does
        return original(*args, **kwargs)

    monkeypatch.setattr(screen, "plot_width_comparison", warn_then_plot)
    screen.main()
    first = capsys.readouterr()
    screen.main()

    text = read(out / logs.LOG_NAME)
    assert text.count(f"INFO     ets-screen: start: {' '.join(argv)}") == 2
    assert text.count("INFO     ets-screen: done in") == 2
    assert "INFO     R-05 Current land-cover proxy is potentially plantable: " in text
    assert "INFO     reject rate " in text
    assert "WARNING  " in text and "UserWarning: Tight layout not applied" in text
    # The manifest is the result and stays on stdout; the log goes to stderr.
    assert json.loads(first.out)["feature_count"] == 12
    assert "ets-screen: start" in first.err and "ets-screen" not in first.out


def test_a_crash_keeps_its_traceback_in_the_run_log_only(tmp_path, monkeypatch, capsys):
    out = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", ["ets-screen", "--demo", "--output", str(out)])

    def broken(*args, **kwargs):
        return 1 / 0

    monkeypatch.setattr(screen, "evaluate_rules", broken)
    with pytest.raises(ZeroDivisionError):
        screen.main()

    text = read(out / logs.LOG_NAME)
    assert "ERROR    rules: failed after" in text
    assert "ERROR    ets-screen: failed after" in text
    assert text.count("Traceback (most recent call last)") == 1 and "1 / 0" in text
    err = capsys.readouterr().err
    assert "ERROR    ets-screen: failed after" in err and "Traceback" not in err


# ------------------------------------------------------------------ review labels


@pytest.fixture
def review_dir(tmp_path):
    pd.DataFrame({"unit_id": ["unit-a", "unit-b"]}).to_csv(
        tmp_path / "review_sample_ids.csv", index=False
    )
    return tmp_path


def test_ingest_logs_the_pending_state_and_prints_the_summary(review_dir, info, capsys):
    assert ingest.main(["--review-dir", str(review_dir)]) == 0
    assert "review_labels.csv not present; writing the pending-review summary." in messages(info)
    assert "pending_independent_human_review" in capsys.readouterr().out
    assert (review_dir / "review_summary.csv").exists()


def test_ingest_logs_rejected_labels_as_an_error(review_dir, info):
    pd.DataFrame(
        {
            "unit_id": ["unit-a", "unit-b"],
            "review_label": ["plausible-plantable", "already-forested"],
            "reviewer": ["Claude", "Claude"],
            "review_date": ["2026-10-30", "2026-10-30"],
            "evidence_note": ["Open pasture with no visible constraint."] * 2,
        }
    ).to_csv(review_dir / "review_labels.csv", index=False)

    assert ingest.main(["--review-dir", str(review_dir)]) == 1
    (error,) = messages(info, logging.ERROR)
    # This review_dir has no current review_version.json, so the labels are
    # refused before their content is read (test_review_labels.py covers each
    # reason). Whatever the reason, the refusal is logged as an error.
    assert error.startswith("review labels rejected: the review sample or imagery cards are out of date")
    assert not (review_dir / "review_summary.csv").exists()


# ------------------------------------------------------------------ downloads


def squares(count, **columns):
    return gpd.GeoDataFrame(
        {"OBJECTID": range(1, count + 1), **columns},
        geometry=[box(i * 20, 0, i * 20 + 10, 10) for i in range(count)],
        crs=2193,
    )


def requested(params):
    return [int(value) for value in params["objectIds"].split(",")]


def test_download_logs_batch_progress_then_reads_the_cache(tmp_path, monkeypatch, info):
    monkeypatch.setattr(download, "RAW", tmp_path)
    monkeypatch.setattr(download, "_service_info", lambda service: {"max_record_count": 2000})
    monkeypatch.setattr(
        download, "_request_json",
        lambda url, params, post=False: {
            "objectIds": list(range(1, 1201)), "objectIdFieldName": "OBJECTID"
        },
    )
    # The downloader checks that each batch returns exactly the IDs it asked for.
    every = squares(1200)
    monkeypatch.setattr(
        download, "_query_geojson",
        lambda service, params: every[every["OBJECTID"].isin(requested(params))],
    )
    service = "https://example.invalid/arcgis/rest/services/Land_Cover/FeatureServer/0"
    frame, _ = download._cached_download("lcdb_test", service, (0, 0, 1, 1), "OBJECTID")
    assert len(frame) == 1200
    got = messages(info)
    assert "lcdb_test: 1,200 features in the bounding box, 3 batches of 500" in got
    assert [m for m in got if re.fullmatch(r"lcdb_test: [\d,]+/1,200", m)] == [
        "lcdb_test: 500/1,200", "lcdb_test: 1,000/1,200", "lcdb_test: 1,200/1,200"]
    assert any(re.fullmatch(r"download lcdb_test: done in \d+\.\d s", m) for m in got)
    assert f"lcdb_test: 1,200 features cached at {logs.rel(tmp_path / 'lcdb_test.gpkg')}" in got

    info.clear()
    # The cache must not touch the network.
    monkeypatch.setattr(download, "_request_json", None)
    monkeypatch.setattr(download, "_service_info", None)
    download._cached_download("lcdb_test", service, (0, 0, 1, 1), "OBJECTID")
    assert messages(info) == [
        f"lcdb_test: 1,200 features read from the cache at {logs.rel(tmp_path / 'lcdb_test.gpkg')}"
    ]


def test_download_main_logs_each_step(tmp_path, monkeypatch, info, capsys):
    raw, processed = tmp_path / "raw", tmp_path / "processed"
    monkeypatch.setattr(download, "RAW", raw)
    monkeypatch.setattr(download, "PROCESSED", processed)
    layers = {
        download.LCDB_URL: gpd.GeoDataFrame(
            {
                "OBJECTID": [1, 2, 3],
                "LCDB_UID": ["lcdb1", "lcdb2", "lcdb3"],
                "Name_2023": ["Low Producing Grassland"] * 3,
                "Class_2023": [41] * 3,
            },
            # lcdb3 is a 0.25 m2 sliver: a clipping fragment to discard.
            geometry=[box(100, 100, 300, 300), box(400, 400, 700, 700), box(0, 0, 0.5, 0.5)],
            crs=2193,
        ),
        download.LUCAS_URL: squares(1, LUCID_1989=["72"], LUCID_2007=["72"], LUCID_2020=["72"]),
        download.DOC_URL: squares(1, Name=["Reserve"]),
    }

    def query(service, params):
        if service == download.BOUNDARY_URL:
            return gpd.GeoDataFrame(
                {"TA2026_V1_00_NAME": ["Gisborne District"]},
                geometry=[box(0, 0, 1000, 1000)],
                crs=2193,
            )
        layer = layers[service]
        return layer[layer["OBJECTID"].isin(requested(params))]

    def object_ids(url, params, post=False):
        layer = layers[url.removesuffix("/query")]
        return {"objectIds": layer["OBJECTID"].tolist(), "objectIdFieldName": "OBJECTID"}

    monkeypatch.setattr(download, "_query_geojson", query)
    monkeypatch.setattr(download, "_request_json", object_ids)
    monkeypatch.setattr(download, "_service_info", lambda service: {"url": service})
    download.main()

    got = messages(info)
    for name in ("gisborne_boundary", "lcdb_v60_screening_bbox", "lucas_v005_bbox",
                 "doc_conservation_bbox"):
        assert any(re.fullmatch(rf"download {name}: done in \d+\.\d s", m) for m in got), name
    assert (
        "candidates: 3 single-part polygons of the selected LCDB classes in the district, "
        "1 fragments below 1 m2 discarded, 2 units kept"
    ) in got
    assert "pre-1990 evidence: 1 LUCAS polygons; conservation: 1 DOC polygons" in got
    assert any(re.fullmatch(r"write processed inputs: done in \d+\.\d s", m) for m in got)
    manifest = json.loads(capsys.readouterr().out)
    assert manifest["feature_counts"]["gisborne_candidates.gpkg"] == 2
    assert manifest["discarded_clip_fragments_below_1_m2"] == 1


def test_review_cards_log_their_progress(tmp_path, monkeypatch, info):
    queue = gpd.GeoDataFrame(
        {"unit_id": [f"u{i:02d}" for i in range(30)], "lcdb_class": ["Low Producing Grassland"] * 30},
        geometry=[box(i * 100, 0, i * 100 + 50, 50) for i in range(30)],
        crs=2193,
    )
    queue.to_file(tmp_path / "queue.gpkg", layer="review_queue", driver="GPKG")
    monkeypatch.setattr(cards, "_draw_card", lambda row, attribution: Image.new("RGB", (8, 8)))
    monkeypatch.setattr(
        cards, "_imagery_source",
        lambda: {"copyright_text": "test imagery", "retrieved_at": "2026-10-30T00:00:00Z"},
    )
    monkeypatch.setattr(
        sys, "argv",
        ["download_review_cards.py", "--queue", str(tmp_path / "queue.gpkg"),
         "--output", str(tmp_path / "cards")],
    )
    cards.main()
    progress = [m for m in messages(info) if re.fullmatch(r"review cards: \d\d/30 u\d\d", m)]
    assert progress[0] == "review cards: 01/30 u00" and progress[-1] == "review cards: 30/30 u29"
    assert len(progress) == 30
    assert f"review cards: 30 cards and 3 contact sheets in {logs.rel(tmp_path / 'cards')}" in messages(info)
