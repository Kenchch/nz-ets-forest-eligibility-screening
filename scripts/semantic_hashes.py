"""Write or verify platform-tolerant hashes of committed GeoPackage content."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

import geopandas as gpd
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "gisborne"
MANIFEST = OUTPUT / "semantic_hashes.json"
FILES = ("candidates.gpkg", "quarantine.gpkg", "review/review_queue.gpkg")


def semantic_hash(path: Path) -> str:
    frame = gpd.read_file(path)
    geometry_name = frame.geometry.name
    columns = sorted(column for column in frame.columns if column != geometry_name)
    rows: list[str] = []
    for _, row in frame.sort_values("parcel_id").iterrows():
        attributes = []
        for column in columns:
            value = row[column]
            if pd.isna(value):
                value = None
            elif hasattr(value, "item"):
                value = value.item()
            attributes.append(value)
        geometry = row[geometry_name]
        payload = {"attributes": attributes, "geometry_wkb_hex": geometry.wkb_hex}
        rows.append(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str))
    return sha256("\n".join(rows).encode("utf-8")).hexdigest()


def current() -> dict[str, str]:
    return {relative: semantic_hash(OUTPUT / relative) for relative in FILES}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    values = current()
    if args.write:
        MANIFEST.write_text(json.dumps(values, indent=2) + "\n", encoding="utf-8")
        print(MANIFEST)
        return
    expected = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if values != expected:
        raise SystemExit(f"semantic output mismatch:\nexpected={expected}\nactual={values}")
    for relative, digest in values.items():
        print(f"ok  {relative}  {digest}")


if __name__ == "__main__":
    main()
