"""Deterministic output helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path


FIXED_TIMESTAMP = "2026-09-12T00:00:00.000Z"

# SQLite stamps the writing library's version into the database header. That
# makes an otherwise identical GeoPackage differ byte-for-byte between machines,
# so every rerun rewrote the committed evidence and grew the repository history.
# Bytes 92-95 are "version-valid-for" and 96-99 are SQLITE_VERSION_NUMBER; both
# are advisory. Zeroing the first makes readers reload the schema rather than
# trust a cached copy, which is the safe direction.
_VERSION_HEADER_OFFSET = 92
_VERSION_HEADER = (0).to_bytes(4, "big") + (0).to_bytes(4, "big")


def normalise_gpkg(path: str | Path) -> None:
    """Remove volatile GeoPackage timestamps and compact the database."""

    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE gpkg_contents SET last_change = ?", (FIXED_TIMESTAMP,))
        connection.commit()
        connection.execute("VACUUM")
    _strip_sqlite_version_header(path)


def _strip_sqlite_version_header(path: str | Path) -> None:
    """Blank the writing library's version stamp in the SQLite header."""

    with open(path, "r+b") as handle:
        handle.seek(_VERSION_HEADER_OFFSET)
        handle.write(_VERSION_HEADER)
