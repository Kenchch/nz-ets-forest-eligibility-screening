"""Deterministic output helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path


FIXED_TIMESTAMP = "2026-09-12T00:00:00.000Z"

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


def normalise_gpkg(path: str | Path) -> None:
    """Remove volatile GeoPackage timestamps and compact the database."""

    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE gpkg_contents SET last_change = ?", (FIXED_TIMESTAMP,))
        connection.commit()
        connection.execute("VACUUM")
    connection.close()
    _stabilise_sqlite_header(path)


def _stabilise_sqlite_header(path: str | Path) -> None:
    """Pin the run- and machine-dependent fields of the SQLite header."""

    with open(path, "r+b") as handle:
        handle.seek(_CHANGE_COUNTER_OFFSET)
        handle.write(_CHANGE_COUNTER)
        handle.seek(_VERSION_HEADER_OFFSET)
        handle.write(_VERSION_HEADER)
