import pandas as pd

from ets_screening.demo_data import build_demo_layers
from ets_screening.rules import evaluate_rules


def by_id(results, parcel_id):
    return results.set_index("parcel_id").loc[parcel_id]


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


def test_rule_audit_has_eight_rows_per_feature():
    candidates, pre1990, conservation = build_demo_layers()
    _, audit = evaluate_rules(candidates, pre1990, conservation)
    counts = audit.groupby("parcel_id")["rule_id"].nunique()
    assert (counts == 8).all()

