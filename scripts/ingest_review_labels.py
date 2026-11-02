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
from hashlib import sha256
import logging
from pathlib import Path
import tempfile

import pandas as pd

from ets_screening import logs
from ets_screening.review_labels import (
    ReviewLabelError,
    load_review_labels,
    load_review_sample_ids,
    require_current_review_version,
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
    return load_review_sample_ids(pinned)


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    """Publish complete CSV bytes; failed writes leave existing evidence intact."""

    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="", dir=path.parent, suffix=".tmp", delete=False
    ) as handle:
        temporary = Path(handle.name)
        try:
            frame.to_csv(handle, index=False, lineterminator="\n")
        except BaseException:
            handle.close()
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-dir", type=Path, default=REVIEW)
    args = parser.parse_args(argv)

    review_dir = args.review_dir
    labels_path = review_dir / "review_labels.csv"
    try:
        expected = sample_unit_ids(review_dir)
        labels_sha256 = None
        if labels_path.exists():
            require_current_review_version(review_dir)
            labels = load_review_labels(labels_path, expected)
            labels_sha256 = sha256(labels_path.read_bytes()).hexdigest()
            log.info(
                f"review labels: {len(labels)} of {len(expected)} accepted from "
                f"{'; '.join(sorted(set(labels['reviewer'])))}"
            )
        else:
            labels = None
            log.info(f"{labels_path.name} not present; writing the pending-review summary.")
        summary = summarise_review_labels(labels, len(expected), IMAGERY, labels_sha256)
    except ReviewLabelError as error:
        log.error(f"review labels rejected: {error}")
        return 1

    # The reviewer's own file is evidence and is never rewritten; its hash in
    # the summary ties the published numbers to those exact bytes.
    _write_csv(summary, review_dir / "review_summary.csv")
    log.info(f"review labels: wrote {logs.rel(review_dir / 'review_summary.csv')}")
    print(summary.to_string(index=False))
    return 0


if __name__ == "__main__":
    with logs.command("ingest_review_labels", RUN_LOG):
        raise SystemExit(main())
