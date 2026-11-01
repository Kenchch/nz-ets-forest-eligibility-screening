import pandas as pd
import pytest

from ets_screening.demo_data import build_demo_layers
from ets_screening.review_labels import (
    ReviewLabelError,
    load_review_labels,
    load_review_sample_ids,
    summarise_review_labels,
)
from ets_screening.sample_review import write_review_bundle


UNIT_IDS = ["unit-a", "unit-b", "unit-c"]


def _labels(**overrides) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "unit_id": UNIT_IDS,
            "review_label": [
                "plausible-plantable",
                "already-forested",
                "clearly-not-plantable",
            ],
            "reviewer": ["Feng Jiang"] * 3,
            "review_date": ["2026-09-14"] * 3,
            "evidence_note": [
                "Open pasture with no visible built or water constraint.",
                "Closed woody canopy covers most of the polygon.",
                "Polygon follows an active braided riverbed margin.",
            ],
        }
    )
    for column, value in overrides.items():
        frame[column] = value
    return frame


def _write(tmp_path, frame):
    path = tmp_path / "review_labels.csv"
    frame.to_csv(path, index=False)
    return path


def test_accepts_a_completed_human_review(tmp_path):
    labels = load_review_labels(_write(tmp_path, _labels()), UNIT_IDS)
    assert list(labels["unit_id"]) == sorted(UNIT_IDS)
    assert set(labels["reviewer"]) == {"Feng Jiang"}


@pytest.mark.parametrize(
    "reviewer",
    [
        "Codex visual review",
        "Claude",
        "GPT-4 vision",
        "AI reviewer",
        "automated triage",
        "review bot",
    ],
)
def test_rejects_machine_reviewers(tmp_path, reviewer):
    path = _write(tmp_path, _labels(reviewer=reviewer))
    with pytest.raises(ReviewLabelError, match="looks automated"):
        load_review_labels(path, UNIT_IDS)


def test_accepts_a_person_whose_name_contains_a_flagged_substring(tmp_path):
    # The pattern is word-bounded, so real names are not caught by "ai" in
    # "Maia" or "bot" in "Botha".
    labels = load_review_labels(
        _write(tmp_path, _labels(reviewer=["Maia Botha", "Rangi Ngata", "Maia Botha"])),
        UNIT_IDS,
    )
    assert len(labels) == 3


def test_rejects_labels_outside_the_vocabulary(tmp_path):
    path = _write(tmp_path, _labels(review_label="probably-fine"))
    with pytest.raises(ReviewLabelError, match="outside the vocabulary"):
        load_review_labels(path, UNIT_IDS)


def test_rejects_a_sample_that_does_not_match_the_pinned_queue(tmp_path):
    path = _write(tmp_path, _labels(unit_id=["unit-a", "unit-b", "unit-z"]))
    with pytest.raises(ReviewLabelError, match="do not match the committed review sample"):
        load_review_labels(path, UNIT_IDS)


def test_rejects_blank_cells(tmp_path):
    path = _write(tmp_path, _labels(evidence_note=["", "x" * 30, "y" * 30]))
    with pytest.raises(ReviewLabelError, match="blank cells"):
        load_review_labels(path, UNIT_IDS)


def test_rejects_an_uninformative_evidence_note(tmp_path):
    path = _write(tmp_path, _labels(evidence_note="looks ok"))
    with pytest.raises(ReviewLabelError, match="at least 20 characters"):
        load_review_labels(path, UNIT_IDS)


def test_rejects_a_non_iso_review_date(tmp_path):
    path = _write(tmp_path, _labels(review_date="14/09/2026"))
    with pytest.raises(ReviewLabelError, match="ISO YYYY-MM-DD"):
        load_review_labels(path, UNIT_IDS)


def test_rejects_a_duplicated_unit(tmp_path):
    path = _write(tmp_path, _labels(unit_id=["unit-a", "unit-a", "unit-c"]))
    with pytest.raises(ReviewLabelError, match="duplicate unit_id"):
        load_review_labels(path, UNIT_IDS)


def test_pending_summary_reports_no_rate():
    summary = summarise_review_labels(None, 30, "imagery")
    metrics = dict(zip(summary["metric"], summary["value"]))
    assert metrics["review_status"] == "pending_independent_human_review"
    assert metrics["labels_recorded"] == "0"
    assert not any(metric.startswith("visual_") for metric in metrics)


def test_completed_summary_reports_the_agreement_rate():
    summary = summarise_review_labels(_labels(), 3, "imagery")
    metrics = dict(zip(summary["metric"], summary["value"]))
    assert metrics["review_status"] == "complete"
    assert metrics["visual_agreement_rate"] == "0.3333"
    assert metrics["reviewer"] == "Feng Jiang"


def test_review_bundle_pins_the_sample(tmp_path):
    candidates, _, _ = build_demo_layers()
    write_review_bundle(candidates, tmp_path, sample_size=2)

    pinned = pd.read_csv(tmp_path / "review_sample_ids.csv", dtype=str)
    template = pd.read_csv(tmp_path / "review_labels_template.csv", dtype=str)
    assert list(pinned["unit_id"]) == list(template["unit_id"])
    assert template.drop(columns="unit_id").isna().all().all()


@pytest.mark.parametrize("column", ["unit_id", "reviewer", "evidence_note"])
def test_rejects_whitespace_only_required_cells(tmp_path, column):
    with pytest.raises(ReviewLabelError, match="blank cells"):
        load_review_labels(_write(tmp_path, _labels(**{column: " \t "})))


@pytest.mark.parametrize("value", ["20260914", "2026-W38-1", "2026-02-30"])
def test_rejects_noncanonical_or_invalid_dates(tmp_path, value):
    with pytest.raises(ReviewLabelError, match="ISO YYYY-MM-DD"):
        load_review_labels(_write(tmp_path, _labels(review_date=value)))


def test_rejects_duplicate_ids_after_trimming(tmp_path):
    with pytest.raises(ReviewLabelError, match="duplicate unit_id"):
        load_review_labels(_write(tmp_path, _labels(unit_id=["unit-a", " unit-a ", "unit-c"])))


def test_rejects_repeated_ids_in_expected_sample(tmp_path):
    with pytest.raises(ReviewLabelError, match="duplicate unit_id"):
        load_review_labels(_write(tmp_path, _labels()), UNIT_IDS + ["unit-a"])


def test_rejects_extra_csv_fields_instead_of_inferring_an_index(tmp_path):
    path = tmp_path / "review_labels.csv"
    path.write_text(
        "unit_id,review_label,reviewer,review_date,evidence_note\n"
        "extra,unit-a,plausible-plantable,Feng Jiang,2026-09-14,Open pasture visible throughout\n",
        encoding="utf-8",
    )
    with pytest.raises(ReviewLabelError, match="expected 5 cells"):
        load_review_labels(path)


def test_csv_parse_errors_have_review_label_error_type(tmp_path):
    path = tmp_path / "review_labels.csv"
    path.write_text('unit_id,review_label,reviewer,review_date,evidence_note\n"unclosed', encoding="utf-8")
    with pytest.raises(ReviewLabelError, match="cannot read review CSV"):
        load_review_labels(path)


def test_pinned_ids_preserve_literal_na(tmp_path):
    path = tmp_path / "review_sample_ids.csv"
    path.write_text("unit_id\nNA\n001\n", encoding="utf-8")
    assert load_review_sample_ids(path) == ["NA", "001"]


@pytest.mark.parametrize("body", ["unit_id\na\na\n", 'unit_id\n" "\n', "wrong\na\n"])
def test_rejects_invalid_pinned_sample_csv(tmp_path, body):
    path = tmp_path / "review_sample_ids.csv"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(ReviewLabelError):
        load_review_sample_ids(path)


def test_summary_cannot_mark_partial_labels_complete():
    with pytest.raises(ReviewLabelError, match="sample size"):
        summarise_review_labels(_labels(), 30, "imagery")


def test_summary_rejects_empty_completed_labels():
    with pytest.raises(ReviewLabelError, match="no rows"):
        summarise_review_labels(_labels().iloc[:0], 0, "imagery")


def test_rejects_compatibility_unicode_machine_name(tmp_path):
    with pytest.raises(ReviewLabelError, match="looks automated"):
        load_review_labels(_write(tmp_path, _labels(reviewer="Ｃｏｄｅｘ")))


@pytest.mark.parametrize(
    "reviewer",
    [
        "ClaudeAgent",
        "ReviewBot",
        "GPTBot",
        "Assistant9000",
        "Grok",
        "xAI",
        "AutoGPT",
        "claudeagent",
        "C.h.a.t.G.P.T",
        "SyntheticReviewer",
    ],
)
def test_rejects_machine_names_that_defeat_word_boundaries(tmp_path, reviewer):
    # A \b(...)\b regex misses every one of these: concatenating two trigger
    # words, appending a digit, or splitting one with punctuation all remove the
    # word boundary the pattern depends on.
    with pytest.raises(ReviewLabelError, match="looks automated"):
        load_review_labels(_write(tmp_path, _labels(reviewer=reviewer)))


@pytest.mark.parametrize(
    "reviewer",
    ["Botha", "Abbott", "Llamas", "Marc Laudens", "Bartholomew Bardsley", "Wiremu Tane"],
)
def test_accepts_real_names_containing_machine_substrings(tmp_path, reviewer):
    # Substring matching on the short, ambiguous words ("bot", "llama", "bard")
    # would reject all of these, so those are matched as whole tokens only.
    labels = load_review_labels(_write(tmp_path, _labels(reviewer=reviewer)))
    assert set(labels["reviewer"]) == {reviewer}


# --- Review version gate and stratified sampling -------------------------------


def test_labels_on_a_stale_sample_or_cards_are_refused(tmp_path):
    import json

    from ets_screening.review_labels import (
        CARD_RENDERER,
        REVIEW_VERSION_FILE,
        SAMPLE_ALGORITHM,
        ReviewLabelError,
        require_current_review_version,
    )

    with pytest.raises(ReviewLabelError, match="out of date"):
        require_current_review_version(tmp_path)
    version = tmp_path / REVIEW_VERSION_FILE
    version.write_text(json.dumps({"sample_algorithm": SAMPLE_ALGORITHM, "card_renderer": None}), encoding="utf-8")
    with pytest.raises(ReviewLabelError, match="card_renderer"):
        require_current_review_version(tmp_path)
    version.write_text(
        json.dumps({"sample_algorithm": SAMPLE_ALGORITHM, "card_renderer": CARD_RENDERER}), encoding="utf-8"
    )
    require_current_review_version(tmp_path)


def test_fresh_sample_records_its_version_and_needs_new_cards(tmp_path):
    import json

    from ets_screening.review_labels import REVIEW_VERSION_FILE, SAMPLE_ALGORITHM

    candidates, _, _ = build_demo_layers()
    write_review_bundle(candidates, tmp_path, sample_size=3)
    version = json.loads((tmp_path / REVIEW_VERSION_FILE).read_text(encoding="utf-8"))
    assert version["sample_algorithm"] == SAMPLE_ALGORITHM
    assert version["card_renderer"] is None
    assert version["sampling_frame_count"] == len(candidates)


def test_sample_includes_flagged_candidates():
    from ets_screening.sample_review import MIN_FLAGGED_IN_SAMPLE, select_review_sample

    candidates, _, _ = build_demo_layers()
    frame = pd.concat([candidates.assign(unit_id=candidates["unit_id"] + f"-{copy}") for copy in range(10)])
    frame = frame.set_geometry("geometry").reset_index(drop=True)
    frame["advisory_rule_ids"] = ""
    frame.loc[frame.index[:6], "advisory_rule_ids"] = "R-03-low-overlap"
    first = select_review_sample(frame, sample_size=30, seed=7)
    flagged = first["advisory_rule_ids"].ne("").sum()
    assert flagged == MIN_FLAGGED_IN_SAMPLE
    assert len(first) == 30
    again = select_review_sample(frame.sample(frac=1, random_state=3), sample_size=30, seed=7)
    assert again["unit_id"].tolist() == first["unit_id"].tolist()
