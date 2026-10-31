"""Validate a completed human imagery review and rebuild the review summary.

Workflow:

    cp outputs/gisborne/review/review_labels_template.csv \
       outputs/gisborne/review/review_labels.csv
    # label all 30 cards in outputs/gisborne/review/cards/
    python scripts/ingest_review_labels.py
    python scripts/reproduce.py

The script refuses machine-generated labels: the imagery review is the part of
this project that must be done, and signed, by a named person.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

from ets_screening import logs
from ets_screening.review_labels import (
    ReviewLabelError,
    load_review_labels,
    summarise_review_labels,
)


ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "outputs" / "gisborne" / "review"
IMAGERY = "Gisborne District Council Imagery Satellite Gisborne 2024 (credited to LINZ)"
RUN_LOG = ROOT / "outputs" / logs.LOG_NAME

log = logging.getLogger("ets_screening.ingest_review_labels")


def sample_unit_ids(review_dir: Path) -> list[str]:
    pinned = review_dir / "review_sample_ids.csv"
    if not pinned.exists():
        raise ReviewLabelError(f"pinned review sample not found: {pinned}")
    return pd.read_csv(pinned, dtype=str)["unit_id"].tolist()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-dir", type=Path, default=REVIEW)
    args = parser.parse_args(argv)

    review_dir = args.review_dir
    expected = sample_unit_ids(review_dir)
    labels_path = review_dir / "review_labels.csv"

    if labels_path.exists():
        try:
            labels = load_review_labels(labels_path, expected)
        except ReviewLabelError as error:
            log.error(f"review labels rejected: {error}")
            return 1
        log.info(
            f"review labels: {len(labels)} of {len(expected)} accepted from "
            f"{'; '.join(sorted(set(labels['reviewer'])))}"
        )
        labels.to_csv(labels_path, index=False)
    else:
        labels = None
        log.info(f"{labels_path.name} not present; writing the pending-review summary.")

    summary = summarise_review_labels(labels, len(expected), IMAGERY)
    summary.to_csv(review_dir / "review_summary.csv", index=False)
    log.info(f"review labels: wrote {logs.rel(review_dir / 'review_summary.csv')}")
    print(summary.to_string(index=False))
    return 0


if __name__ == "__main__":
    with logs.command("ingest_review_labels", RUN_LOG):
        raise SystemExit(main())
