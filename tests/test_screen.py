import geopandas as gpd
import pandas as pd
import pytest

from ets_screening.demo_data import build_demo_layers
from ets_screening.screen import RejectRateExceeded, run_screening


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
