"""Deterministic output helpers."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import os
import sqlite3
from pathlib import Path


#: Fallback build time for generated files. SOURCE_DATE_EPOCH (the
#: reproducible-builds convention, e.g. `git log -1 --format=%ct`) overrides
#: it, so a published output can carry the date of the commit it came from
#: while reruns of one commit stay byte-identical.
DEFAULT_BUILD_EPOCH = 1_789_171_200  # 2026-09-12T00:00:00Z


def build_datetime() -> datetime:
    """Return the fixed build time used in file metadata."""

    value = os.environ.get("SOURCE_DATE_EPOCH", "").strip()
    epoch = int(value) if value.isdigit() else DEFAULT_BUILD_EPOCH
    return datetime.fromtimestamp(epoch, tz=timezone.utc)


def build_timestamp() -> str:
    """Return build_datetime() in the GeoPackage timestamp format."""

    return build_datetime().strftime("%Y-%m-%dT%H:%M:%S.000Z")


# The SQLite header carries two volatile fields that make an otherwise identical
# GeoPackage differ byte-for-byte, so reruns rewrote the committed evidence:
#
# - Bytes 24-27, the file change counter, count write transactions. GDAL batches
#   its commits partly by timing, so the count varies between runs of the same
#   code on the same machine.
# - Bytes 92-95 ("version-valid-for") and 96-99 (SQLITE_VERSION_NUMBER) record
#   the writing library, so they vary between machines.
#
# All are advisory for a closed file. version-valid-for is zeroed so it never
# matches the change counter; SQLite then derives the database size from the
# file itself rather than trusting the in-header copy, which is the safe
# direction.
_CHANGE_COUNTER_OFFSET = 24
_CHANGE_COUNTER = (1).to_bytes(4, "big")
_VERSION_HEADER_OFFSET = 92
_VERSION_HEADER = (0).to_bytes(4, "big") + (0).to_bytes(4, "big")


class PublicationRecoveryError(RuntimeError):
    """Previous output files remain in staging after a failed rollback."""


def publish_outputs(stage: Path, output_dir: Path) -> None:
    """Replace generated files, restoring the previous run on a write failure.

    Only files produced by this run are managed. Assessor figures, labels and
    imagery alongside them must survive a refresh. Callers must retain staging
    if PublicationRecoveryError is raised, because it contains recovery copies.
    """
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    generated = sorted(path for path in stage.rglob("*") if path.is_file())
    backup_dir = stage / ".previous"
    backed_up: list[tuple[Path, Path]] = []
    installed: list[Path] = []
    try:
        for source in generated:
            relative = source.relative_to(stage)
            target = output_dir / relative
            # Reject nested links instead of following them outside the run.
            if not target.resolve().is_relative_to(output_dir):
                raise ValueError(f"output path escapes the output directory: {target}")
            if target.is_symlink() or any(
                parent.is_symlink() for parent in target.parents if parent != output_dir
                and parent.is_relative_to(output_dir)
            ):
                raise ValueError(f"output path must not be a symbolic link: {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if not target.is_file():
                    raise ValueError(f"expected an output file: {target}")
                backup = backup_dir / relative
                backup.parent.mkdir(parents=True, exist_ok=True)
                os.replace(target, backup)
                backed_up.append((target, backup))
            os.replace(source, target)
            installed.append(target)
    except BaseException:
        try:
            for target in reversed(installed):
                target.unlink()
            for target, backup in reversed(backed_up):
                os.replace(backup, target)
        except OSError as error:
            raise PublicationRecoveryError(
                f"could not restore every output; previous files are retained in {backup_dir}"
            ) from error
        raise


def normalise_gpkg(path: str | Path) -> None:
    """Remove volatile fields from a closed GeoPackage without creating files."""

    # mode=rw fails for a missing input rather than creating an empty database.
    # closing is required: sqlite's context manager manages transactions only.
    uri = Path(path).resolve().as_uri() + "?mode=rw"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        # Header edits below apply to the main file, so all database pages must
        # be there, not in a WAL journal belonging to another open connection.
        journal_mode = connection.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
        if journal_mode != "delete":
            raise ValueError("GeoPackage must be closed before normalisation")
        connection.execute("UPDATE gpkg_contents SET last_change = ?", (build_timestamp(),))
        connection.commit()
        connection.execute("VACUUM")
    _stabilise_sqlite_header(path)


def _stabilise_sqlite_header(path: str | Path) -> None:
    """Pin the run- and machine-dependent fields of the SQLite header."""

    with open(path, "r+b") as handle:
        header = handle.read(100)
        if len(header) != 100 or header[:16] != b"SQLite format 3\x00":
            raise ValueError("not a SQLite database; refusing to modify its header")
        handle.seek(_CHANGE_COUNTER_OFFSET)
        handle.write(_CHANGE_COUNTER)
        handle.seek(_VERSION_HEADER_OFFSET)
        handle.write(_VERSION_HEADER)
