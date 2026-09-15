"""Validate and summarise the independent human imagery review.

The imagery review is the one step in this project that a machine must not
perform. Rule R-05 only proves that the *mapped* land-cover class is a
plausible proxy; deciding whether a polygon is physically plantable at the
imagery date is an interpretation task, and a screening tool that reports a
machine's interpretation as a review result overstates its own evidence.

`load_review_labels` therefore rejects a label file whose reviewer looks
automated, so committed review evidence stays traceable to a named person.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
import re

import pandas as pd


REVIEW_COLUMNS = ("unit_id", "review_label", "reviewer", "review_date", "evidence_note")

LABEL_VOCABULARY = ("plausible-plantable", "already-forested", "clearly-not-plantable")

#: A reviewer must be a person. Assistant, model and agent names are refused so
#: machine-generated labels cannot re-enter the committed evidence chain.
MACHINE_REVIEWER_PATTERN = re.compile(
    r"\b("
    r"ai|a\.i|agent|assistant|automat\w*|bot|chatgpt|claude|codex|copilot|gemini|"
    r"gpt|llm|machine|model|robot|script|synthetic"
    r")\b",
    re.IGNORECASE,
)

MINIMUM_EVIDENCE_NOTE_CHARACTERS = 20


class ReviewLabelError(ValueError):
    """Raised when a review label file is not usable as human evidence."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReviewLabelError(message)


def load_review_labels(
    path: str | Path,
    expected_unit_ids: list[str] | None = None,
) -> pd.DataFrame:
    """Read completed review labels, or raise `ReviewLabelError`.

    `expected_unit_ids` pins the file to the committed fixed-seed sample so a
    reviewer cannot quietly label a different, easier set of polygons.
    """

    path = Path(path)
    _require(path.exists(), f"review label file not found: {path}")
    labels = pd.read_csv(path, dtype=str, keep_default_na=False)

    _require(
        tuple(labels.columns) == REVIEW_COLUMNS,
        f"expected columns {REVIEW_COLUMNS}, found {tuple(labels.columns)}",
    )
    _require(len(labels) > 0, "review label file has no rows")

    blank_rows = labels.index[labels.eq("").any(axis=1)].tolist()
    _require(
        not blank_rows,
        "every column must be completed; blank cells on CSV lines "
        f"{[row + 2 for row in blank_rows]}",
    )

    duplicates = labels.loc[labels["unit_id"].duplicated(), "unit_id"].tolist()
    _require(not duplicates, f"duplicate unit_id values: {sorted(set(duplicates))}")

    if expected_unit_ids is not None:
        expected = set(map(str, expected_unit_ids))
        actual = set(labels["unit_id"])
        _require(
            actual == expected,
            "labels do not match the committed review sample; "
            f"missing={sorted(expected - actual)} unexpected={sorted(actual - expected)}",
        )

    unknown = sorted(set(labels["review_label"]) - set(LABEL_VOCABULARY))
    _require(
        not unknown,
        f"review_label values {unknown} are outside the vocabulary {LABEL_VOCABULARY}",
    )

    machine = sorted(
        {
            reviewer
            for reviewer in labels["reviewer"]
            if MACHINE_REVIEWER_PATTERN.search(reviewer)
        }
    )
    _require(
        not machine,
        f"reviewer {machine} looks automated. The imagery review must be carried "
        "out and signed by a named person; a machine label is not review evidence.",
    )

    for index, value in labels["review_date"].items():
        try:
            date.fromisoformat(value)
        except ValueError as error:
            raise ReviewLabelError(
                f"review_date {value!r} on CSV line {index + 2} is not ISO YYYY-MM-DD"
            ) from error

    short = labels.index[
        labels["evidence_note"].str.len() < MINIMUM_EVIDENCE_NOTE_CHARACTERS
    ].tolist()
    _require(
        not short,
        "each evidence_note must record what was actually visible (at least "
        f"{MINIMUM_EVIDENCE_NOTE_CHARACTERS} characters); CSV lines "
        f"{[row + 2 for row in short]} are too short",
    )

    return labels.sort_values("unit_id").reset_index(drop=True)


def summarise_review_labels(
    labels: pd.DataFrame | None,
    sample_size: int,
    imagery: str,
) -> pd.DataFrame:
    """Build `review_summary.csv` for either the pending or completed state."""

    if labels is None:
        return pd.DataFrame(
            [
                ("sample_size", str(sample_size)),
                ("review_status", "pending_independent_human_review"),
                ("labels_recorded", "0"),
                ("imagery", imagery),
                (
                    "how_to_complete",
                    "Copy review_labels_template.csv to review_labels.csv, label all "
                    f"{sample_size} cards from review/cards/, then run "
                    "python scripts/ingest_review_labels.py",
                ),
            ],
            columns=["metric", "value"],
        )

    counts = labels["review_label"].value_counts()
    plausible = int(counts.get("plausible-plantable", 0))
    reviewers = sorted(set(labels["reviewer"]))
    return pd.DataFrame(
        [
            ("sample_size", str(sample_size)),
            ("review_status", "complete"),
            ("labels_recorded", str(len(labels))),
            ("plausible_plantable", str(plausible)),
            ("already_forested", str(int(counts.get("already-forested", 0)))),
            ("clearly_not_plantable", str(int(counts.get("clearly-not-plantable", 0)))),
            ("visual_agreement_rate", f"{plausible / len(labels):.4f}"),
            ("visual_false_positive_rate", f"{1 - plausible / len(labels):.4f}"),
            ("reviewer", "; ".join(reviewers)),
            ("review_date_first", min(labels["review_date"])),
            ("review_date_last", max(labels["review_date"])),
            ("imagery", imagery),
            (
                "limitation",
                "Single-reviewer interpretation of one imagery date; no ground truth "
                "and no second-reviewer agreement measurement",
            ),
        ],
        columns=["metric", "value"],
    )
