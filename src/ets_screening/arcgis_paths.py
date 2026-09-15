r"""Translate ArcGIS catalog paths into something GDAL can open.

ArcGIS addresses a feature class inside a container workspace as
``<workspace>\<name>`` -- for example ``gisborne.gpkg\main.units`` or
``gisborne.gdb\units``. GDAL wants the container and the layer name as two
separate arguments, so a toolbox parameter cannot be handed to
``geopandas.read_file`` unchanged.

This module deliberately does not import ``arcpy``: the translation is pure
string handling, so it stays testable in CI where ArcGIS is not installed.
"""

from __future__ import annotations

from pathlib import PurePath

#: Workspace types that hold named layers inside a single filesystem entry.
CONTAINER_SUFFIXES = (".gpkg", ".gdb", ".sqlite", ".geodatabase")

#: ArcGIS prefixes GeoPackage layers with the SQLite schema name.
_GPKG_SCHEMA_PREFIX = "main."


def split_dataset_path(path: str | PurePath) -> tuple[str, str | None]:
    """Split an ArcGIS dataset path into ``(container, layer)``.

    A path that is not inside a container workspace is returned unchanged with
    a ``None`` layer, so plain shapefiles and single-layer GeoPackages keep
    working exactly as before.
    """

    pure = PurePath(str(path))
    for parent in pure.parents:
        if parent.suffix.lower() not in CONTAINER_SUFFIXES:
            continue
        layer = pure.relative_to(parent).as_posix()
        if parent.suffix.lower() == ".gpkg" and layer.startswith(_GPKG_SCHEMA_PREFIX):
            layer = layer[len(_GPKG_SCHEMA_PREFIX):]
        return str(parent), layer
    return str(pure), None
