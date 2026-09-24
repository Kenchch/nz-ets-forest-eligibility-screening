from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import GeometryCollection, LineString, MultiPolygon, Point, box

from ets_screening.demo_data import build_demo_layers
from ets_screening.load import InputValidationError
from ets_screening.rules import RuleConfig, evaluate_rules, load_rule_register


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

    manual = audit[audit["rule_id"].isin(["R-06", "R-07", "R-08", "R-09", "R-10", "R-11"])]
    assert manual["passed"].isna().all()
    assert (manual["outcome"] == "manual").all()
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


def test_rule_audit_has_one_row_per_register_rule_per_feature():
    candidates, pre1990, conservation = build_demo_layers()
    _, audit = evaluate_rules(candidates, pre1990, conservation)
    register = load_rule_register()
    counts = audit.groupby("unit_id")["rule_id"].nunique()
    assert (counts == len(register)).all()
    assert audit["rule_id"].head(len(register)).tolist() == register["rule_id"].tolist()


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


@pytest.mark.parametrize(
    "name",
    [
        "minimum_area_ha",
        "width_threshold_m",
        "minimum_overlap_area_m2",
        "minimum_overlap_pct",
        "clip_required_overlap_m2",
        "sliver_width_m",
        "adjacency_distance_m",
    ],
)
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), -1, True, "1"])
def test_rule_config_rejects_unsafe_numeric_thresholds(name, value):
    with pytest.raises(ValueError, match=name):
        RuleConfig(**{name: value})


@pytest.mark.parametrize("name", ["minimum_area_ha", "width_threshold_m"])
def test_area_and_width_thresholds_must_be_positive(name):
    with pytest.raises(ValueError, match=name):
        RuleConfig(**{name: 0})


def test_overlap_percentage_cannot_exceed_one_hundred():
    with pytest.raises(ValueError, match="minimum_overlap_pct"):
        RuleConfig(minimum_overlap_pct=101)


@pytest.mark.parametrize("overlay_name", ["pre1990", "conservation"])
@pytest.mark.parametrize("geometry", [Point(50, 50), LineString([(0, 0), (100, 100)]), GeometryCollection([box(0, 0, 100, 100)])])
def test_nonpolygonal_overlays_fail_instead_of_silently_passing(overlay_name, geometry):
    candidates = gpd.GeoDataFrame(
        {"unit_id": ["A"], "lcdb_class": ["Low Producing Grassland"]},
        geometry=[box(0, 0, 100, 100)],
        crs=2193,
    )
    empty = gpd.GeoDataFrame(geometry=[], crs=2193)
    overlays = {"pre1990": empty, "conservation": empty}
    overlays[overlay_name] = gpd.GeoDataFrame(geometry=[geometry], crs=2193)
    with pytest.raises(InputValidationError, match=overlay_name):
        evaluate_rules(candidates, **overlays)


def test_overlapping_and_multipart_overlay_records_are_unioned():
    candidates = gpd.GeoDataFrame(
        {"unit_id": ["A"], "lcdb_class": ["Low Producing Grassland"]},
        geometry=[box(0, 0, 100, 100)],
        crs=2193,
    )
    overlay = gpd.GeoDataFrame(
        geometry=[box(0, 0, 50, 100), MultiPolygon([box(25, 0, 75, 100), box(200, 0, 300, 100)])],
        crs=2193,
    )
    empty = gpd.GeoDataFrame(geometry=[], crs=2193)
    result, _ = evaluate_rules(candidates, overlay, empty)
    assert result.iloc[0]["pre1990_overlap_m2"] == 7500
    assert result.iloc[0]["pre1990_overlap_pct"] == 75


def test_custom_thresholds_are_reflected_in_audit_names():
    candidates = gpd.GeoDataFrame(
        {"unit_id": ["A"], "lcdb_class": ["Low Producing Grassland"]},
        geometry=[box(0, 0, 100, 50)],
        crs=2193,
    )
    empty = gpd.GeoDataFrame(geometry=[], crs=2193)
    result, audit = evaluate_rules(candidates, empty, empty, RuleConfig(minimum_area_ha=2, width_threshold_m=60))
    assert result.iloc[0]["failed_rule_ids"] == "R-01|R-02"
    names = audit.set_index("rule_id")["rule_name"]
    assert names["R-01"] == "Area at least 1 hectare (configured: 2 ha)"
    assert names["R-02"] == "Average width at least 30 metres (configured: 60 m)"


def test_zero_overlap_thresholds_still_allow_boundary_only_contact():
    candidates = gpd.GeoDataFrame(
        {"unit_id": ["A"], "lcdb_class": ["Low Producing Grassland"]},
        geometry=[box(0, 0, 100, 100)],
        crs=2193,
    )
    touching = gpd.GeoDataFrame(geometry=[box(100, 0, 200, 100)], crs=2193)
    result, _ = evaluate_rules(
        candidates, touching, touching,
        RuleConfig(minimum_overlap_area_m2=0, minimum_overlap_pct=0),
    )
    assert result.iloc[0]["status"] == "candidate_review"


# --- Threshold boundary tests -------------------------------------------------
#
# Each rule's comparison operator sits on a boundary that no fixture elsewhere in
# the suite lands on, so `>=` could be flipped to `>` (or the reverse) without a
# single test failing. These pin the operators themselves.


def _frame(geometry, unit_id="boundary", lcdb_class="Low Producing Grassland"):
    return gpd.GeoDataFrame(
        {"unit_id": [unit_id], "lcdb_class": [lcdb_class]},
        geometry=[geometry],
        crs=2193,
    )


def _empty():
    return gpd.GeoDataFrame(geometry=[], crs=2193)


def test_exactly_one_hectare_passes_r01():
    # 100 m x 100 m is exactly 10,000 m2. R-01 is "at least 1 hectare", so this
    # must pass; flipping `>=` to `>` would silently quarantine a 1.00 ha parcel.
    results, _ = evaluate_rules(_frame(box(0, 0, 100, 100)), _empty(), _empty())
    row = by_id(results, "boundary")
    assert row["area_ha"] == 1.0
    assert bool(row["r01_area_pass"])


def test_exactly_thirty_metre_strip_passes_r02():
    # The statute excludes an average width *less than* 30 m. Eroding by the
    # full 15 m left nothing of a 30.000 m strip, so the effective threshold was
    # slightly above 30 m; the erosion tolerance keeps this strip.
    results, _ = evaluate_rules(_frame(box(0, 0, 500, 30)), _empty(), _empty())
    row = by_id(results, "boundary")
    assert bool(row["width_core_pass"])
    assert row["width_rect_m"] == pytest.approx(30.0)
    assert bool(row["r02_width_proxy_pass"])


def test_just_under_thirty_metre_strip_fails_r02():
    results, _ = evaluate_rules(_frame(box(0, 0, 500, 29.99)), _empty(), _empty())
    row = by_id(results, "boundary")
    assert not bool(row["width_core_pass"])
    assert not bool(row["r02_width_proxy_pass"])


def test_straight_strip_just_over_thirty_metres_passes_r02():
    # 2A/P reads 29.77 m for this 1 ha, 33 m wide strip and used to quarantine
    # it. The equivalent rectangle recovers the true 33 m width.
    results, _ = evaluate_rules(_frame(box(0, 0, 304, 33)), _empty(), _empty())
    row = by_id(results, "boundary")
    assert row["width_ap_m"] < 30
    assert row["width_rect_m"] == pytest.approx(33.0)
    assert row["failed_rule_ids"] == ""


@pytest.mark.parametrize("rule_column", ["r03_no_pre1990_overlap", "r04_no_conservation_overlap"])
def test_overlap_of_exactly_one_square_metre_is_not_material(rule_column):
    # A 10 m x 10 m candidate is 100 m2, so a 1 m2 overlay is simultaneously
    # exactly the 1 m2 area bound and exactly the 1% proportion bound. The area
    # bound is exclusive (`> 1`), so this must NOT be material; flipping it to
    # `>=` would start excluding units on a single square metre. The sliver
    # filter is disabled so it cannot hide the operator under test.
    overlay = gpd.GeoDataFrame(geometry=[box(0, 0, 1, 1)], crs=2193)
    pre1990 = overlay if rule_column.startswith("r03") else _empty()
    conservation = overlay if rule_column.startswith("r04") else _empty()
    results, _ = evaluate_rules(
        _frame(box(0, 0, 10, 10)), pre1990, conservation, RuleConfig(sliver_width_m=0)
    )
    row = by_id(results, "boundary")
    assert row["pre1990_overlap_m2" if rule_column.startswith("r03") else "conservation_overlap_m2"] == 1.0
    assert bool(row[rule_column])


@pytest.mark.parametrize("rule_column", ["r03_no_pre1990_overlap", "r04_no_conservation_overlap"])
def test_overlap_of_exactly_one_percent_is_material(rule_column):
    # 2,500 m2 of a 250,000 m2 candidate is exactly 1%, well clear of the 1 m2
    # bound and below the 1 ha absolute bound. The proportion bound is inclusive
    # (`>= 1%`), so this IS material; flipping it to `>` would demote a genuine
    # 1% overlap to advisory. Mitred opening keeps the square's full area.
    overlay = gpd.GeoDataFrame(geometry=[box(0, 0, 50, 50)], crs=2193)
    pre1990 = overlay if rule_column.startswith("r03") else _empty()
    conservation = overlay if rule_column.startswith("r04") else _empty()
    results, _ = evaluate_rules(_frame(box(0, 0, 500, 500)), pre1990, conservation)
    row = by_id(results, "boundary")
    column = "pre1990_overlap_pct" if rule_column.startswith("r03") else "conservation_overlap_pct"
    assert row[column] == 1.0
    assert not bool(row[rule_column])


def test_material_conservation_overlap_excludes_the_unit():
    # R-04 is the only rule whose material finding drives status all the way to
    # "excluded", so pin that transition rather than just the boolean.
    conservation = gpd.GeoDataFrame(geometry=[box(0, 0, 100, 100)], crs=2193)
    results, _ = evaluate_rules(_frame(box(0, 0, 1000, 1000)), _empty(), conservation)
    assert by_id(results, "boundary")["status"] == "excluded"


def test_minor_conservation_overlap_is_advisory_not_exclusion():
    # 5,000 m2 of 1,000,000 m2 is 0.5%: above the 1 m2 bound, below the 1% bound.
    conservation = gpd.GeoDataFrame(geometry=[box(0, 0, 100, 50)], crs=2193)
    results, _ = evaluate_rules(_frame(box(0, 0, 1000, 1000)), _empty(), conservation)
    row = by_id(results, "boundary")
    assert bool(row["r04_no_conservation_overlap"])
    assert row["advisory_rule_ids"] == "R-04-low-overlap"
    assert row["status"] != "excluded"


def test_both_low_overlaps_are_joined_in_the_advisory_trail():
    minor = gpd.GeoDataFrame(geometry=[box(0, 0, 100, 50)], crs=2193)
    results, _ = evaluate_rules(_frame(box(0, 0, 1000, 1000)), minor, minor)
    assert by_id(results, "boundary")["advisory_rule_ids"] == "R-03-low-overlap|R-04-low-overlap"


# --- Materiality, contiguity and audit-table semantics -------------------------


@pytest.mark.parametrize("overlay_name, flag", [("pre1990", "R-03"), ("conservation", "R-04")])
def test_one_hectare_overlap_below_one_percent_requires_clipping(overlay_name, flag):
    # 1.5 ha of a 400 ha unit is 0.375%. It is not mapping noise, but excluding
    # the whole 400 ha unit for it would be the opposite error: the unit stays
    # in review, flagged, and the conflict leaves its conflict-free area.
    overlay = gpd.GeoDataFrame(geometry=[box(0, 0, 150, 100)], crs=2193)
    layers = {"pre1990": _empty(), "conservation": _empty(), overlay_name: overlay}
    results, audit = evaluate_rules(_frame(box(0, 0, 2000, 2000)), **layers)
    row = by_id(results, "boundary")
    assert row["status"] == "candidate_review"
    assert row["advisory_rule_ids"] == f"{flag}-clip-required"
    assert row["conflict_free_area_ha"] == pytest.approx(398.5)
    rule = audit.set_index("rule_id").loc[flag]
    assert rule["outcome"] == "advisory"
    assert pd.isna(rule["passed"])


def test_conflict_free_area_does_not_double_count_shared_overlap():
    shared = gpd.GeoDataFrame(geometry=[box(0, 0, 150, 100)], crs=2193)
    results, _ = evaluate_rules(_frame(box(0, 0, 2000, 2000)), shared, shared)
    assert by_id(results, "boundary")["conflict_free_area_ha"] == pytest.approx(398.5)


def test_narrow_boundary_sliver_does_not_exclude_a_small_unit():
    # A 10 m wide strip along the edge of a 2 ha unit is 5% of it, but no part
    # of the overlap is 15 m wide: this is generalisation noise, not land.
    sliver = gpd.GeoDataFrame(geometry=[box(0, 0, 10, 200)], crs=2193)
    results, audit = evaluate_rules(_frame(box(0, 0, 100, 200)), _empty(), sliver)
    row = by_id(results, "boundary")
    assert row["conservation_overlap_pct"] == 10
    assert row["conservation_overlap_core_m2"] == 0
    assert row["status"] == "candidate_review"
    assert row["advisory_rule_ids"] == "R-04-low-overlap"
    r04 = audit.set_index("rule_id").loc["R-04"]
    assert r04["outcome"] == "advisory"
    assert pd.isna(r04["passed"])
    assert "overlap_m2=2000.00" in r04["observed"]


def _frames(*rows):
    return gpd.GeoDataFrame(
        {"unit_id": [row[0] for row in rows], "lcdb_class": [row[2] for row in rows]},
        geometry=[row[1] for row in rows],
        crs=2193,
    )


def test_small_unit_meets_r01_through_a_touching_plantable_neighbour():
    units = _frames(
        ("small", box(0, 0, 80, 80), "Low Producing Grassland"),
        ("large", box(80, 0, 200, 100), "Low Producing Grassland"),
    )
    results, _ = evaluate_rules(units, _empty(), _empty())
    row = by_id(results, "small")
    assert not bool(row["r01_area_pass"])
    assert row["contiguous_plantable_ha"] == pytest.approx(1.84)
    assert row["status"] == "candidate_review"
    assert row["advisory_rule_ids"] == "R-01-contiguous"


def test_neighbour_beyond_adjacency_distance_does_not_count():
    units = _frames(
        ("small", box(0, 0, 80, 80), "Low Producing Grassland"),
        ("large", box(100, 0, 220, 100), "Low Producing Grassland"),
    )
    results, _ = evaluate_rules(units, _empty(), _empty())
    assert by_id(results, "small")["failed_rule_ids"] == "R-01"


def test_non_plantable_neighbour_does_not_count():
    units = _frames(
        ("small", box(0, 0, 80, 80), "Low Producing Grassland"),
        ("urban", box(80, 0, 200, 100), "Built-up Area (settlement)"),
    )
    results, _ = evaluate_rules(units, _empty(), _empty())
    assert by_id(results, "small")["failed_rule_ids"] == "R-01"


def test_narrow_strip_meets_r02_only_next_to_a_qualifying_area():
    strip = ("strip", box(0, 0, 600, 20), "Low Producing Grassland")
    alone, _ = evaluate_rules(_frames(strip), _empty(), _empty())
    assert "R-02" in by_id(alone, "strip")["failed_rule_ids"]

    anchored, audit = evaluate_rules(
        _frames(strip, ("block", box(0, 20, 120, 140), "Low Producing Grassland")),
        _empty(),
        _empty(),
    )
    row = by_id(anchored, "strip")
    assert row["status"] == "candidate_review"
    assert row["advisory_rule_ids"] == "R-02-contiguous"
    strip_audit = audit[audit["unit_id"] == "strip"].set_index("rule_id")
    assert strip_audit.loc["R-02", "outcome"] == "advisory"
    assert strip_audit.loc["R-01", "outcome"] == "pass"


def test_units_just_over_one_hectare_are_flagged_near_threshold():
    results, audit = evaluate_rules(_frame(box(0, 0, 100, 102)), _empty(), _empty())
    row = by_id(results, "boundary")
    assert row["status"] == "candidate_review"
    assert row["advisory_rule_ids"] == "R-01-near-threshold"
    assert audit.set_index("rule_id").loc["R-01", "outcome"] == "advisory"


def test_audit_testability_comes_from_the_register():
    candidates, pre1990, conservation = build_demo_layers()
    _, audit = evaluate_rules(candidates, pre1990, conservation)
    testable = audit.drop_duplicates("rule_id").set_index("rule_id")["testable_from_open_data"]
    register = load_rule_register().set_index("rule_id")["testable_from_open_data"]
    assert testable.to_dict() == register.to_dict()
    assert testable["R-02"] == "proxy"
    assert testable["R-03"] == "partial"


def test_packaged_register_matches_documented_register():
    root = Path(__file__).resolve().parents[1]
    packaged = root / "src" / "ets_screening" / "rule_register.csv"
    documented = root / "rules" / "rule_register.csv"
    assert packaged.read_bytes() == documented.read_bytes()


def test_manual_review_ids_follow_the_register():
    candidates, pre1990, conservation = build_demo_layers()
    results, _ = evaluate_rules(candidates, pre1990, conservation)
    assert (results["manual_review_rule_ids"] == "R-03|R-06|R-07|R-08|R-09|R-10|R-11").all()


def test_unknown_plantable_class_names_are_reported():
    config = RuleConfig(plantable_lcdb_classes=frozenset({"Low Producing Grassland", "Low Producing Grasland"}))
    with pytest.warns(UserWarning, match="Low Producing Grasland"):
        evaluate_rules(_frame(box(0, 0, 120, 120)), _empty(), _empty(), config)


def _lucas(*rows):
    return gpd.GeoDataFrame(
        {"LUCID_1989": [row[0] for row in rows], "LUCID_2007": [row[1] for row in rows]},
        geometry=[row[2] for row in rows],
        crs=2193,
    )


@pytest.mark.parametrize(
    "lucid_1989, lucid_2007",
    [
        ("71 - Natural Forest", "71 - Natural Forest"),
        ("72 - Planted Forest - Pre 1990", "72 - Planted Forest - Pre 1990"),
        ("71 - Natural Forest", "72 - Planted Forest - Pre 1990"),
    ],
)
def test_forest_in_1989_and_2007_is_material_for_r03(lucid_1989, lucid_2007):
    evidence = _lucas((lucid_1989, lucid_2007, box(0, 0, 60, 60)))
    results, _ = evaluate_rules(_frame(box(0, 0, 120, 120)), evidence, _empty())
    row = by_id(results, "boundary")
    assert row["failed_rule_ids"] == "R-03"


def test_forest_deforested_by_2007_is_advisory_not_material():
    # Para (a)(ii): forest land on 31 December 1989 deforested by 2007 may
    # still be post-1989 forest land, so this needs a person, not a rule.
    evidence = _lucas(("71 - Natural Forest", "75 - Grassland - High producing", box(0, 0, 60, 60)))
    results, audit = evaluate_rules(_frame(box(0, 0, 120, 120)), evidence, _empty())
    row = by_id(results, "boundary")
    assert row["status"] == "candidate_review"
    assert row["pre1990_overlap_m2"] == 0
    assert row["pre1990_deforested_overlap_m2"] == 3600
    assert row["advisory_rule_ids"] == "R-03-deforested-1990-2007"
    assert audit.set_index("rule_id").loc["R-03", "outcome"] == "advisory"


def test_evidence_that_was_not_forest_in_1989_is_ignored():
    evidence = _lucas(("75 - Grassland - High producing", "72 - Planted Forest - Post 1989", box(0, 0, 60, 60)))
    results, _ = evaluate_rules(_frame(box(0, 0, 120, 120)), evidence, _empty())
    row = by_id(results, "boundary")
    assert row["failed_rule_ids"] == ""
    assert row["advisory_rule_ids"] == ""
