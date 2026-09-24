"""Validate and summarise the independent human imagery review.

The imagery review is the one step in this project that a machine must not
perform. Rule R-05 only proves that the *mapped* land-cover class is a
plausible proxy; deciding whether a polygon is physically plantable at the
imagery date is an interpretation task, and a screening tool that reports a
machine's interpretation as a review result overstates its own evidence.

`load_review_labels` rejects recognisable machine-style reviewer names. This
heuristic does not authenticate identities or establish who performed a review.
"""

from __future__ import annotations

import csv
from datetime import date
import json
from numbers import Integral
from pathlib import Path
import re
import unicodedata

import pandas as pd


REVIEW_COLUMNS = ("unit_id", "review_label", "reviewer", "review_date", "evidence_note")

LABEL_VOCABULARY = ("plausible-plantable", "already-forested", "clearly-not-plantable")

#: Review must be performed by a person. Recognisable assistant, model and agent
#: names are refused as a heuristic; ordinary names are not proof of human work.
#:
#: A single ``\b(...)\b`` regex is not enough: ``\b`` needs a non-word character
#: on both sides of the trigger, so simply concatenating two trigger words
#: (``ClaudeAgent``) or appending a digit (``Assistant9000``) silently defeats
#: it. The reviewer string is therefore tokenised first — on separators *and* on
#: camel-case boundaries — and each token is tested.
#:
#: Product names are matched as a substring of a token; this deliberately broad
#: policy can also reject real names. Short, ambiguous words are matched as a
#: whole token only, because substring matching on them would reject real names
#: ("Botha", "Abbott", "Llamas").
_MACHINE_SUBSTRINGS = frozenset(
    {
        "anthropic",
        "assistant",
        "autogpt",
        "automat",
        "chatbot",
        "chatglm",
        "chatgpt",
        "claude",
        "codex",
        "copilot",
        "deepseek",
        "gemini",
        "gpt",
        "grok",
        "huggingface",
        "llm",
        "openai",
        "perplexity",
        "qwen",
    }
)

_MACHINE_TOKENS = frozenset(
    {
        "ai",
        "agent",
        "auto",
        "bard",
        "bot",
        "haiku",
        "llama",
        "machine",
        "mistral",
        "model",
        "opus",
        "robot",
        "script",
        "sonnet",
        "synthetic",
    }
)

#: Long enough that an accidental collision inside a real name is implausible,
#: so these are also tested against the punctuation-stripped whole string. That
#: closes the ``C.h.a.t.G.P.T`` style of evasion without risking a false
#: positive from two adjacent name parts running together.
_MACHINE_UNAMBIGUOUS = frozenset(
    {
        "anthropic",
        "autogpt",
        "chatgpt",
        "copilot",
        "deepseek",
        "huggingface",
        "openai",
        "perplexity",
    }
)

_TOKEN_PATTERN = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z]+|[a-z]+|[0-9]+")


def _reviewer_tokens(reviewer: str) -> list[str]:
    """Split a reviewer name into case-folded, accent-free tokens."""

    normalised = unicodedata.normalize("NFKD", unicodedata.normalize("NFKC", reviewer))
    stripped = "".join(char for char in normalised if not unicodedata.combining(char))
    return [token.casefold() for token in _TOKEN_PATTERN.findall(stripped)]


def looks_automated(reviewer: str) -> bool:
    """Return whether a reviewer name looks like a machine rather than a person.

    Deliberately conservative: it fails closed. A small number of real names
    ("Ai Weiwei", "Claude Monet") are refused because the words they contain are
    also model names. Adding name components does not necessarily resolve these
    matches; affected reviewers need maintainer review of the policy. This is a
    heuristic only: an ordinary-looking name does not authenticate a person or
    establish that the imagery was reviewed by a human.
    """

    tokens = _reviewer_tokens(reviewer)
    if any(token in _MACHINE_TOKENS for token in tokens):
        return True
    if any(needle in token for token in tokens for needle in _MACHINE_SUBSTRINGS):
        return True
    joined = "".join(tokens)
    return any(needle in joined for needle in _MACHINE_UNAMBIGUOUS)

MINIMUM_EVIDENCE_NOTE_CHARACTERS = 20
#: The review queue and its cards were first published on this date, so no
#: genuine label can predate it.
EARLIEST_REVIEW_DATE = date(2026, 9, 12)

#: Leading characters that Excel and LibreOffice treat as the start of a formula.
#: `review_labels.csv` is rewritten in place and `review_summary.csv` is written
#: from it, so a note beginning `=HYPERLINK(...)` would execute for whoever opens
#: the committed evidence. Quote-prefixing is the usual mitigation, but this file
#: is read back by the pipeline, so a prefix would corrupt the evidence instead.
#: Refusing the value keeps the round trip exact. A leading "-" is deliberately
#: allowed: it only ever yields a number or an error, never a call, and notes
#: written as "- open pasture ..." are a plausible human habit.
_CSV_FORMULA_PREFIXES = ("=", "+", "@", "\t", "\r")
_FREE_TEXT_COLUMNS = ("reviewer", "evidence_note")


class ReviewLabelError(ValueError):
    """Raised when a review label file is not usable as human evidence."""


#: Written beside review_sample_ids.csv. The sampler records how the sample
#: was drawn and the card renderer records how the cards were drawn.
REVIEW_VERSION_FILE = "review_version.json"
#: Labels are accepted as evidence only for a sample and cards produced by
#: these versions. The legacy sample excluded advisory candidates, and the
#: legacy cards drew their crosshair at the tile centre, off the unit.
SAMPLE_ALGORITHM = "stratified-sha256-rank-v2"
CARD_RENDERER = "interior-point-crosshair-v2"


def load_review_version(review_dir: str | Path) -> dict[str, object]:
    path = Path(review_dir) / REVIEW_VERSION_FILE
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ReviewLabelError(f"cannot read {path}: {error}") from error
    _require(isinstance(value, dict), f"{path} must hold a JSON object")
    return value


def require_current_review_version(review_dir: str | Path) -> None:
    """Refuse labels made on a stale sample or stale imagery cards."""

    version = load_review_version(review_dir)
    stale = []
    if version.get("sample_algorithm") != SAMPLE_ALGORITHM:
        stale.append(f"sample_algorithm is {version.get('sample_algorithm')!r}, expected {SAMPLE_ALGORITHM!r}")
    if version.get("card_renderer") != CARD_RENDERER:
        stale.append(f"card_renderer is {version.get('card_renderer')!r}, expected {CARD_RENDERER!r}")
    _require(
        not stale,
        "the review sample or imagery cards are out of date ("
        + "; ".join(stale)
        + "). Re-draw the sample with `python scripts/reproduce.py --resample-review` and "
        "re-render the cards with `python scripts/download_review_cards.py` before labelling.",
    )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReviewLabelError(message)


def _read_review_csv(path: str | Path, columns: tuple[str, ...]) -> pd.DataFrame:
    """Read strict CSV without pandas' implicit-index or missing-value inference."""

    path = Path(path)
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle, strict=True)
            header = next(reader, [])
            _require(
                tuple(header) == columns,
                f"expected columns {columns}, found {tuple(header)}",
            )
            rows = []
            for row in reader:
                _require(
                    len(row) == len(columns),
                    f"expected {len(columns)} cells on CSV line {reader.line_num}, "
                    f"found {len(row)}",
                )
                rows.append(row)
    except (OSError, UnicodeError, csv.Error) as error:
        raise ReviewLabelError(f"cannot read review CSV {path}: {error}") from error
    return pd.DataFrame(rows, columns=columns)


def validate_review_sample_ids(unit_ids: list[str]) -> list[str]:
    """Reject missing or repeated IDs before set comparison can hide them."""

    ids = pd.Series(unit_ids, dtype=object)
    _require(not ids.isna().any(), "review sample has blank unit_id values")
    ids = ids.astype(str).str.strip()
    _require(not ids.eq("").any(), "review sample has blank unit_id values")
    duplicates = ids[ids.duplicated()].tolist()
    _require(not duplicates, f"duplicate unit_id values in review sample: {duplicates}")
    return ids.tolist()


def load_review_sample_ids(path: str | Path) -> list[str]:
    """Load the pinned queue, preserving literal identifiers such as `NA`."""

    return validate_review_sample_ids(_read_review_csv(path, ("unit_id",))["unit_id"].tolist())


def load_review_labels(
    path: str | Path,
    expected_unit_ids: list[str] | None = None,
) -> pd.DataFrame:
    """Read completed review labels, or raise `ReviewLabelError`.

    `expected_unit_ids` pins the file to the committed fixed-seed sample so a
    reviewer cannot quietly label a different, easier set of polygons.
    """

    return _validate_review_labels(_read_review_csv(path, REVIEW_COLUMNS), expected_unit_ids)


def _validate_review_labels(
    labels: pd.DataFrame, expected_unit_ids: list[str] | None = None
) -> pd.DataFrame:

    _require(
        tuple(labels.columns) == REVIEW_COLUMNS,
        f"expected columns {REVIEW_COLUMNS}, found {tuple(labels.columns)}",
    )
    _require(len(labels) > 0, "review label file has no rows")

    labels = labels.copy().reset_index(drop=True)
    labels = labels.fillna("").astype(str).apply(lambda column: column.str.strip())

    blank_rows = labels.index[labels.eq("").any(axis=1)].tolist()
    _require(
        not blank_rows,
        "every column must be completed; blank cells on CSV lines "
        f"{[row + 2 for row in blank_rows]}",
    )

    duplicates = labels.loc[labels["unit_id"].duplicated(), "unit_id"].tolist()
    _require(not duplicates, f"duplicate unit_id values: {sorted(set(duplicates))}")

    if expected_unit_ids is not None:
        expected = set(validate_review_sample_ids(expected_unit_ids))
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

    for column in _FREE_TEXT_COLUMNS:
        risky = [
            row + 2
            for row, value in labels[column].items()
            if value.startswith(_CSV_FORMULA_PREFIXES)
        ]
        _require(
            not risky,
            f"{column} on CSV lines {risky} starts with a spreadsheet formula "
            f"character {_CSV_FORMULA_PREFIXES}; rewrite the text so the committed "
            "evidence cannot execute when opened in a spreadsheet",
        )

    machine = sorted(
        {reviewer for reviewer in labels["reviewer"] if looks_automated(reviewer)}
    )
    _require(
        not machine,
        f"reviewer {machine} looks automated. The imagery review must be carried "
        "out and signed by a named person; a machine label is not review evidence.",
    )

    today = date.today()
    for index, value in labels["review_date"].items():
        try:
            if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
                raise ValueError("non-canonical date")
            parsed = date.fromisoformat(value)
        except ValueError as error:
            raise ReviewLabelError(
                f"review_date {value!r} on CSV line {index + 2} is not ISO YYYY-MM-DD"
            ) from error
        _require(
            EARLIEST_REVIEW_DATE <= parsed <= today,
            f"review_date {value!r} on CSV line {index + 2} must fall between "
            f"{EARLIEST_REVIEW_DATE.isoformat()} (the review queue's creation) and today",
        )

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
    labels_sha256: str | None = None,
) -> pd.DataFrame:
    """Build `review_summary.csv` for either the pending or completed state."""

    _require(
        isinstance(sample_size, Integral) and not isinstance(sample_size, bool) and sample_size >= 0,
        "sample_size must be a non-negative integer",
    )

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

    labels = _validate_review_labels(labels)
    _require(len(labels) == sample_size, "completed labels do not match the review sample size")
    counts = labels["review_label"].value_counts()
    plausible = int(counts.get("plausible-plantable", 0))
    reviewers = sorted(set(labels["reviewer"]))
    if len(reviewers) == 1:
        limitation = (
            "Single-reviewer interpretation of one imagery date; no ground truth "
            "and no second-reviewer agreement measurement"
        )
    else:
        limitation = (
            f"{len(reviewers)} reviewers each labelled different units; one imagery date, "
            "no ground truth and no inter-reviewer agreement measurement"
        )
    rows = [
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
        ("limitation", limitation),
    ]
    if labels_sha256 is not None:
        rows.append(("labels_file_sha256", labels_sha256))
    return pd.DataFrame(rows, columns=["metric", "value"])

