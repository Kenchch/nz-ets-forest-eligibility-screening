r"""Translate ArcGIS catalog paths into something GDAL can open.

ArcGIS addresses a feature class inside a container workspace as
``<workspace>\<name>`` -- for example ``gisborne.gpkg\main.units`` or
``gisborne.gdb\units``. GDAL wants the container and the layer name as two
separate arguments, so a toolbox parameter cannot be handed to
``geopandas.read_file`` unchanged.

This module deliberately does not import ``arcpy``: the translation is pure
string handling, so it stays testable in CI where ArcGIS is not installed.

For the same reason it does not use ``pathlib``. ``PurePath`` resolves to
``PurePosixPath`` off Windows, where a backslash is an ordinary character
rather than a separator, so an ArcGIS catalog path looks like a single
component and the split silently does nothing. Scanning the string keeps the
behaviour identical on every platform, and slicing the original text means a
container keeps whichever separator style it arrived with.
"""

from __future__ import annotations

from pathlib import PurePath

#: Workspace types that hold named layers inside a single filesystem entry.
CONTAINER_SUFFIXES = (".gpkg", ".gdb", ".sqlite", ".geodatabase")

#: ArcGIS prefixes GeoPackage layers with the SQLite schema name.
_GPKG_SCHEMA_PREFIX = "main."

_SEPARATORS = "\\/"


def split_dataset_path(path: str | PurePath) -> tuple[str, str | None]:
    """Split an ArcGIS dataset path into ``(container, layer)``.

    A path that is not inside a container workspace is returned unchanged with
    a ``None`` layer, so plain shapefiles and single-layer GeoPackages keep
    working exactly as before.
    """

    text = str(path)
    lowered = text.lower()

    # Take the deepest container, so a workspace nested inside another still
    # resolves to the one that directly holds the layer.
    boundary = None
    for suffix in CONTAINER_SUFFIXES:
        start = 0
        while True:
            index = lowered.find(suffix, start)
            if index == -1:
                break
            end = index + len(suffix)
            # Only a real component boundary counts: the suffix must be
            # followed by a separator, not by more filename.
            if end < len(text) and text[end] in _SEPARATORS:
                if boundary is None or end > boundary:
                    boundary = end
            start = index + 1

    if boundary is None:
        return text, None

    container = text[:boundary]
    layer = text[boundary + 1:].replace("\\", "/")
    if not layer:
        return container, None
    if container.lower().endswith(".gpkg") and layer.startswith(_GPKG_SCHEMA_PREFIX):
        layer = layer[len(_GPKG_SCHEMA_PREFIX):]
    return container, layer
