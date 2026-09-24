"""Command-line behaviour: exit codes, argument validation and output safety."""

from pathlib import Path
import subprocess
import sys

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from ets_screening import sample_review, screen
from ets_screening.demo_data import build_demo_layers
from ets_screening.load import InputValidationError, validate_candidates

ROOT = Path(__file__).resolve().parents[1]


def _exit_code(main, argv):
    with pytest.raises(SystemExit) as raised:
        main(argv)
    return raised.value.code


def _write_demo(tmp_path, crs=2193):
    candidates, pre1990, conservation = build_demo_layers()
    paths = {}
    for name, frame in (("candidates", candidates), ("pre1990", pre1990), ("conservation", conservation)):
        path = tmp_path / f"{name}.gpkg"
        frame.set_crs(crs, allow_override=True).to_file(path, driver="GPKG")
        paths[name] = str(path)
    return paths


def _args(paths, output):
    return [
        "--candidates", paths["candidates"],
        "--pre1990", paths["pre1990"],
        "--conservation", paths["conservation"],
        "--output", str(output),
    ]


def test_demo_run_succeeds_and_marks_its_output(tmp_path, capsys):
    screen.main(["--demo", "--output", str(tmp_path / "out")])
    assert (tmp_path / "out" / screen.OUTPUT_MARKER).exists()
    assert '"scope"' in capsys.readouterr().out


def test_rerun_into_its_own_output_is_allowed(tmp_path):
    output = tmp_path / "out"
    screen.main(["--demo", "--output", str(output)])
    screen.main(["--demo", "--output", str(output)])


def test_non_empty_foreign_directory_is_refused(tmp_path):
    output = tmp_path / "out"
    (output / "figures").mkdir(parents=True)
    notes = output / "figures" / "important_notes.txt"
    notes.write_text("keep", encoding="utf-8")
    (output / "summary.csv").write_text("mine", encoding="utf-8")
    assert _exit_code(screen.main, ["--demo", "--output", str(output)]) == screen.EXIT_OUTPUT_REFUSED
    assert notes.read_text(encoding="utf-8") == "keep"
    assert (output / "summary.csv").read_text(encoding="utf-8") == "mine"


def test_demo_cannot_silently_ignore_supplied_inputs(tmp_path):
    argv = ["--demo", "--candidates", str(tmp_path / "missing.gpkg"), "--output", str(tmp_path / "out")]
    assert _exit_code(screen.main, argv) == 2


@pytest.mark.parametrize("value", ["5", "-1", "nan", "high"])
def test_reject_rate_threshold_must_be_a_fraction(tmp_path, value):
    argv = ["--demo", "--reject-rate-threshold", value, "--output", str(tmp_path / "out")]
    assert _exit_code(screen.main, argv) == 2


def test_missing_input_file_is_a_clean_error(tmp_path, capsys):
    paths = _write_demo(tmp_path)
    paths["pre1990"] = str(tmp_path / "missing.gpkg")
    assert _exit_code(screen.main, _args(paths, tmp_path / "out")) == screen.EXIT_INPUT_MISSING
    assert "Traceback" not in capsys.readouterr().err


def test_wrong_crs_is_an_input_validation_error(tmp_path, capsys):
    paths = _write_demo(tmp_path, crs=3857)
    assert _exit_code(screen.main, _args(paths, tmp_path / "out")) == screen.EXIT_INPUT_INVALID
    assert "EPSG:2193" in capsys.readouterr().err


def test_reject_rate_gate_has_its_own_exit_code(tmp_path):
    argv = ["--demo", "--reject-rate-threshold", "0.1", "--output", str(tmp_path / "out")]
    assert _exit_code(screen.main, argv) == screen.EXIT_REJECT_RATE


def test_version_is_reported():
    result = subprocess.run(
        [sys.executable, "-m", "ets_screening.screen", "--version"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0
    assert result.stdout.strip()


@pytest.mark.parametrize("size", ["-3", "two"])
def test_review_sample_size_must_be_a_non_negative_integer(tmp_path, size):
    paths = _write_demo(tmp_path)
    argv = [paths["candidates"], "--sample-size", size, "--output", str(tmp_path / "review")]
    assert _exit_code(sample_review.main, argv) == 2


def test_review_sampler_refuses_quarantine_input(tmp_path):
    candidates, _, _ = build_demo_layers()
    candidates["status"] = "quarantine"
    path = tmp_path / "quarantine.gpkg"
    candidates.to_file(path, driver="GPKG")
    assert _exit_code(sample_review.main, [str(path), "--output", str(tmp_path / "review")]) == 3


def test_review_sampler_output_is_byte_stable(tmp_path):
    paths = _write_demo(tmp_path)
    for name in ("first", "second"):
        sample_review.main([paths["candidates"], "--sample-size", "3", "--output", str(tmp_path / name)])
    first = (tmp_path / "first" / "review_queue.gpkg").read_bytes()
    assert first == (tmp_path / "second" / "review_queue.gpkg").read_bytes()


def test_reproduce_help_does_not_run_the_pipeline():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "reproduce.py"), "--help"],
        capture_output=True, text=True, check=False, cwd=ROOT / "scripts", timeout=60,
    )
    assert result.returncode == 0
    assert "Rebuild committed Gisborne" in result.stdout


def test_real_subset_is_not_rejected_as_overlapping():
    # Audit repro: a half sample of the committed candidates used to fail
    # "candidate polygons overlap by 0.000 m2" through float cancellation.
    candidates = gpd.read_file(ROOT / "data" / "processed" / "gisborne_candidates.gpkg")
    validate_candidates(candidates.sample(frac=0.5, random_state=25))


def test_true_overlap_is_still_detected_at_real_coordinates():
    candidates = gpd.read_file(ROOT / "data" / "processed" / "gisborne_candidates.gpkg").head(200)
    first = candidates.geometry.iloc[0]
    overlapping = candidates.iloc[[0]].copy()
    overlapping["unit_id"] = "copy"
    overlapping.geometry = [first.intersection(box(*first.buffer(-1).bounds))]
    with pytest.raises(InputValidationError, match="overlap"):
        validate_candidates(pd.concat([candidates, overlapping], ignore_index=True))
