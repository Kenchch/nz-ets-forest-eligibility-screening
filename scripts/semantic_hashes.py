"""Write or verify platform-tolerant hashes of committed GeoPackage content."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import math
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio
from shapely import normalize, set_precision, to_wkb


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "gisborne"
MANIFEST = OUTPUT / "semantic_hashes.json"
FILES = ("candidates.gpkg", "quarantine.gpkg", "review/review_queue.gpkg")
#: The pinned inputs are also hashed by content. checksums.sha256 pins their
#: bytes, which change with the GDAL version that wrote them; this manifest
#: shows whether a refreshed download differs in content or only in bytes.
INPUTS = ROOT / "data" / "processed"
INPUT_MANIFEST = ROOT / "data" / "semantic_hashes.json"
INPUT_FILES = (
    "gisborne_boundary.gpkg",
    "gisborne_candidates.gpkg",
    "gisborne_conservation.gpkg",
    "gisborne_pre1990_evidence.gpkg",
)
#: Floats are compared to 6 decimals and coordinates to 1 mm, so a last-digit
#: difference between library builds is not reported as changed evidence
#: while any change an assessor could see still is.
FLOAT_DECIMALS = 6
GRID_SIZE_M = 1e-3


def _layers(path: Path) -> list[str]:
    return sorted(str(name) for name, _ in pyogrio.list_layers(path))


def _value(value: object) -> object:
    if value is None or (not isinstance(value, (list, dict, str, bytes)) and pd.isna(value)):
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float):
        return round(value, FLOAT_DECIMALS) if math.isfinite(value) else str(value)
    return value


def _frame_digest(frame: gpd.GeoDataFrame, layer: str) -> list[str]:
    geometry_name = frame.geometry.name
    columns = sorted(column for column in frame.columns if column != geometry_name)
    if "unit_id" in frame.columns and frame["unit_id"].duplicated().any():
        raise SystemExit(f"layer {layer} has duplicate unit_id values")
    # Coordinate values alone do not identify a geometry: the same numbers in a
    # different CRS represent different land. Field names and types likewise
    # carry the meaning of the otherwise anonymous attribute values.
    crs = None
    if frame.crs is not None:
        crs = frame.crs.to_authority() or frame.crs.to_wkt(version="WKT2_2019")
    header = {
        "layer": layer,
        "crs": crs,
        "columns": [[column, str(frame[column].dtype)] for column in columns],
        "geometry_types": sorted(frame.geometry.geom_type.dropna().unique().tolist()),
        "rows": len(frame),
    }
    rows: list[str] = []
    for _, row in frame.iterrows():
        geometry = row[geometry_name]
        wkb = None
        if geometry is not None and not geometry.is_empty:
            wkb = to_wkb(normalize(set_precision(geometry, GRID_SIZE_M)), hex=True, byte_order=1)
        payload = {
            "attributes": [_value(row[column]) for column in columns],
            "geometry_wkb_hex": wkb,
        }
        rows.append(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str))
    return [json.dumps(header, sort_keys=True, separators=(",", ":")), *sorted(rows)]


def semantic_hash(path: Path) -> str:
    lines: list[str] = []
    for layer in _layers(path):
        lines.extend(_frame_digest(gpd.read_file(path, layer=layer), layer))
    return sha256("\n".join(lines).encode("utf-8")).hexdigest()


def current(base: Path = OUTPUT, files: tuple[str, ...] = FILES) -> dict[str, str]:
    return {relative: semantic_hash(base / relative) for relative in files}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    for base, files, manifest in ((INPUTS, INPUT_FILES, INPUT_MANIFEST), (OUTPUT, FILES, MANIFEST)):
        values = current(base, files)
        if args.write:
            manifest.write_text(json.dumps(values, indent=2) + "\n", encoding="utf-8", newline="\n")
            print(manifest)
            continue
        expected = json.loads(manifest.read_text(encoding="utf-8"))
        if values != expected:
            raise SystemExit(f"semantic mismatch in {manifest.name}:\nexpected={expected}\nactual={values}")
        for relative, digest in values.items():
            print(f"ok  {relative}  {digest}")


if __name__ == "__main__":
    main()
