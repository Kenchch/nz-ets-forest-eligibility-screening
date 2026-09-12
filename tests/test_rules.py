import pandas as pd
import geopandas as gpd
from shapely.geometry import box

from ets_screening.demo_data import build_demo_layers
from ets_screening.rules import evaluate_rules


def by_id(results, unit_id):
    return results.set_index("unit_id").loc[unit_id]


def test_each_demo_rule_fails_for_its_own_reason():
    candidates, pre1990, conservation = build_demo_layers()
    results, audit = evaluate_rules(candidates, pre1990, conservation)

    assert not bool(by_id(results, "G03")["r01_area_pass"])
    assert not bool(by_id(results, "G02")["r02_width_proxy_pass"])
    assert not bool(by_id(results, "G07")["r03_no_pre1990_overlap"])
    assert not bool(by_id(results, "G05")["r04_no_conservation_overlap"])
    assert not bool(by_id(results, "G06")["r05_lcdb_proxy_pass"])

    manual = audit[audit["rule_id"].isin(["R-06", "R-07", "R-08"])]
    assert manual["passed"].isna().all()
    assert (manual["observed"] == "manual evidence required").all()


def test_quarantine_preserves_all_features_and_reasons():
    candidates, pre1990, conservation = build_demo_layers()
    results, _ = evaluate_rules(candidates, pre1990, conservation)
    assert len(results) == len(candidates)
    assert by_id(results, "G03")["failed_rule_ids"] == "R-01"
    assert "R-03" in by_id(results, "G07")["failed_rule_ids"]
    assert by_id(results, "G05")["status"] == "excluded"
    assert by_id(results, "G01")["status"] == "candidate_review"
    assert by_id(results, "G04")["status"] == "quarantine"
    assert "R-02" in by_id(results, "G04")["failed_rule_ids"]


def test_rule_audit_has_eight_rows_per_feature():
    candidates, pre1990, conservation = build_demo_layers()
    _, audit = evaluate_rules(candidates, pre1990, conservation)
    counts = audit.groupby("unit_id")["rule_id"].nunique()
    assert (counts == 8).all()


def test_boundary_contact_is_not_polygon_overlap():
    candidates = gpd.GeoDataFrame(
        {"unit_id": ["touch"], "lcdb_class": ["Low Producing Grassland"]},
        geometry=[box(0, 0, 100, 100)],
        crs=2193,
    )
    touching = gpd.GeoDataFrame(geometry=[box(100, 0, 200, 100)], crs=2193)
    distant = gpd.GeoDataFrame(geometry=[box(300, 0, 400, 100)], crs=2193)
    results, _ = evaluate_rules(candidates, touching, distant)
    row = results.iloc[0]
    assert bool(row["r03_no_pre1990_overlap"])
    assert row["pre1990_overlap_m2"] == 0


def test_sub_one_percent_overlap_is_advisory_not_whole_unit_failure():
    candidates = gpd.GeoDataFrame(
        {"unit_id": ["large-unit"], "lcdb_class": ["Low Producing Grassland"]},
        geometry=[box(0, 0, 1000, 1000)],
        crs=2193,
    )
    minor_overlap = gpd.GeoDataFrame(geometry=[box(0, 0, 50, 100)], crs=2193)
    empty = gpd.GeoDataFrame(geometry=[], crs=2193)
    results, _ = evaluate_rules(candidates, minor_overlap, empty)
    row = results.iloc[0]
    assert row["pre1990_overlap_m2"] == 5000
    assert row["pre1990_overlap_pct"] == 0.5
    assert bool(row["r03_no_pre1990_overlap"])
    assert row["advisory_rule_ids"] == "R-03-low-overlap"


def test_unrounded_area_controls_threshold_decision():
    candidates = gpd.GeoDataFrame(
        {"unit_id": ["just-short"], "lcdb_class": ["Low Producing Grassland"]},
        geometry=[box(0, 0, 100, 99.9996)],
        crs=2193,
    )
    empty = gpd.GeoDataFrame(geometry=[], crs=2193)
    results, _ = evaluate_rules(candidates, empty, empty)
    assert results.iloc[0]["area_ha"] == 1.0
    assert not bool(results.iloc[0]["r01_area_pass"])


def test_mutated_copies_trigger_each_target_rule():
    """Start with valid geometry, then damage one input dimension at a time."""

    empty = gpd.GeoDataFrame(geometry=[], crs=2193)

    def evaluate(geometry, lcdb_class="Low Producing Grassland", pre=None, pcl=None):
        frame = gpd.GeoDataFrame(
            {"unit_id": ["copy"], "lcdb_class": [lcdb_class]},
            geometry=[geometry],
            crs=2193,
        )
        return evaluate_rules(frame, pre if pre is not None else empty, pcl if pcl is not None else empty)[0].iloc[0]

    valid = box(0, 0, 120, 120)
    assert evaluate(valid)["failed_rule_ids"] == ""
    assert evaluate(box(0, 0, 50, 100))["failed_rule_ids"] == "R-01"
    assert "R-02" in evaluate(box(0, 0, 20, 600))["failed_rule_ids"]

    overlap = gpd.GeoDataFrame(geometry=[box(10, 10, 80, 80)], crs=2193)
    assert evaluate(valid, pre=overlap)["failed_rule_ids"] == "R-03"
    assert evaluate(valid, pcl=overlap)["status"] == "excluded"
    assert evaluate(valid, lcdb_class="Built-up Area")["failed_rule_ids"] == "R-05"
