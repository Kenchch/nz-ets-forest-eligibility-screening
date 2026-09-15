import geopandas as gpd
import pandas as pd
import pytest

from ets_screening.demo_data import build_demo_layers
from ets_screening.geometry import compare_width_methods
from ets_screening.rules import evaluate_rules
from ets_screening.screen import RejectRateExceeded, _summary, run_screening
from ets_screening.sample_review import select_review_sample


def test_demo_pipeline_writes_auditable_outputs(tmp_path):
    candidates, pre1990, conservation = build_demo_layers()
    manifest = run_screening(candidates, pre1990, conservation, tmp_path, 0.90)
    expected = {
        "candidates.gpkg",
        "quarantine.gpkg",
        "summary.csv",
        "rule_results.csv",
        "width_method_comparison.csv",
        "run_manifest.json",
        "layout_map.pdf",
    }
    assert expected.issubset({path.name for path in tmp_path.iterdir()})
    output_count = len(gpd.read_file(tmp_path / "candidates.gpkg")) + len(
        gpd.read_file(tmp_path / "quarantine.gpkg")
    )
    assert output_count == len(candidates)
    assert manifest["crs"] == "EPSG:2193"
    assert len(pd.read_csv(tmp_path / "rule_results.csv")) == len(candidates) * 8


def test_reject_rate_gate_aborts_before_publication(tmp_path):
    candidates, pre1990, conservation = build_demo_layers()
    with pytest.raises(RejectRateExceeded, match="publication aborted"):
        run_screening(candidates, pre1990, conservation, tmp_path, 0.10)
    assert not tmp_path.exists() or not any(tmp_path.iterdir())


def test_main_pipeline_propagates_linz_api_key(tmp_path, monkeypatch):
    candidates, pre1990, conservation = build_demo_layers()
    monkeypatch.setenv("LINZ_BASEMAP_API_KEY", "test-key-not-secret")
    run_screening(candidates, pre1990, conservation, tmp_path, 0.90)
    html = (tmp_path / "review" / "review_map.html").read_text(encoding="utf-8")
    assert "api=test-key-not-secret" in html
    assert "YOUR_API_KEY" not in html


def test_review_sample_is_stable_when_unselected_rows_are_removed():
    candidates, _, _ = build_demo_layers()
    first = select_review_sample(candidates, sample_size=5, seed=42)
    unselected = set(candidates["unit_id"]) - set(first["unit_id"])
    reduced = candidates[~candidates["unit_id"].isin(list(unselected)[:2])]
    second = select_review_sample(reduced, sample_size=5, seed=42)
    assert first["unit_id"].tolist() == second["unit_id"].tolist()


def test_summary_separates_candidate_advisories():
    candidates, pre1990, conservation = build_demo_layers()
    results, _ = evaluate_rules(candidates, pre1990, conservation)
    results.loc[results["status"] == "candidate_review", "advisory_rule_ids"] = "R-03-low-overlap"
    comparison = compare_width_methods(results)

    summary = dict(_summary(results, comparison).itertuples(index=False, name=None))

    assert int(summary["candidate_review_with_advisory"]) == int(
        (results["status"] == "candidate_review").sum()
    )
    assert int(summary["candidate_review_clean"]) == 0


def test_geopackage_bytes_are_stable_across_runs(tmp_path):
    candidates, pre1990, conservation = build_demo_layers()
    first = tmp_path / "first"
    second = tmp_path / "second"
    run_screening(candidates, pre1990, conservation, first, 0.90)
    run_screening(candidates, pre1990, conservation, second, 0.90)
    # Identical content must produce identical bytes, otherwise every rerun
    # rewrites the committed evidence and inflates the repository history.
    for name in ("candidates.gpkg", "quarantine.gpkg"):
        assert (first / name).read_bytes() == (second / name).read_bytes()
