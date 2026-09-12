"""Deterministic output helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path


FIXED_TIMESTAMP = "2026-09-12T00:00:00.000Z"


def normalise_gpkg(path: str | Path) -> None:
    """Remove volatile GeoPackage timestamps and compact the database."""

    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE gpkg_contents SET last_change = ?", (FIXED_TIMESTAMP,))
        connection.commit()
        connection.execute("VACUUM")
