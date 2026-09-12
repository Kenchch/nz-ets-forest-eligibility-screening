"""Create a fixed-seed assessor review queue and optional LINZ aerial web map."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path

import geopandas as gpd
import pandas as pd

from .load import assert_nztm2000

LINZ_ATTRIBUTION = (
    'LINZ CC BY 4.0 © Imagery Basemap contributors - '
    'https://www.linz.govt.nz/data/linz-data/linz-basemaps/data-attribution'
)


def select_review_sample(
    candidates: gpd.GeoDataFrame,
    sample_size: int = 30,
    seed: int = 20260912,
    sample_ids: list[str] | None = None,
) -> gpd.GeoDataFrame:
    assert_nztm2000(candidates, "review candidates")
    if sample_ids is not None:
        available = candidates.set_index("unit_id", drop=False)
        missing = [unit_id for unit_id in sample_ids if unit_id not in available.index]
        if missing:
            raise ValueError(f"review sample IDs are no longer candidates: {missing}")
        return available.loc[sample_ids].reset_index(drop=True).copy()
    count = min(sample_size, len(candidates))
    # Hash ranking is deterministic by ID, not by row position. Preprocessing
    # changes therefore do not silently replace every review case.
    ranked = candidates.copy()
    ranked["_sample_rank"] = ranked["unit_id"].astype(str).map(
        lambda value: sha256(f"{seed}:{value}".encode("utf-8")).hexdigest()
    )
    return (
        ranked.sort_values("_sample_rank")
        .head(count)
        .drop(columns="_sample_rank")
        .sort_values("unit_id")
    )


def write_review_bundle(
    candidates: gpd.GeoDataFrame,
    destination: str | Path,
    sample_size: int = 30,
    seed: int = 20260912,
    api_key: str | None = None,
    sample_ids: list[str] | None = None,
) -> None:
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    sample = select_review_sample(candidates, sample_size, seed, sample_ids)
    sample.to_file(destination / "review_queue.gpkg", layer="review_queue", driver="GPKG")
    pd.DataFrame(
        {
            "unit_id": sample["unit_id"],
            "review_label": "",
            "reviewer": "",
            "review_date": "",
            "evidence_note": "",
        }
    ).to_csv(destination / "review_labels_template.csv", index=False)

    geojson = json.loads(sample.to_crs(4326).to_json())
    api_key = api_key or os.getenv("LINZ_BASEMAP_API_KEY")
    tile_url = (
        "https://basemaps.linz.govt.nz/v1/tiles/aerial/WebMercatorQuad/"
        "{z}/{x}/{y}.webp"
    )
    if api_key:
        tile_url += f"?api={api_key}"
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>ETS review queue</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>html,body,#map{{height:100%;margin:0}} .note{{background:white;padding:8px}}</style></head>
<body><div id="map"></div><script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const features={json.dumps(geojson)};
const map=L.map('map');
L.tileLayer('{tile_url}',
 {{attribution:'{LINZ_ATTRIBUTION}',maxZoom:22}}).addTo(map);
const layer=L.geoJSON(features,{{style:{{color:'#ff2d55',weight:3,fillOpacity:0.08}},
 onEachFeature:(f,l)=>l.bindPopup('<b>'+f.properties.unit_id+'</b><br>Status: '+f.properties.status)}}).addTo(map);
map.fitBounds(layer.getBounds().pad(0.2));
L.control({{position:'topright'}}).onAdd=function(){{const d=L.DomUtil.create('div','note');
d.innerHTML='<b>Human review queue</b><br>Inspect imagery and assign one label: plausible-plantable / already-forested / clearly-not-plantable.<br>Record your name, date and evidence note; AI suggestions are not an accuracy assessment.';return d;}}.addTo(map);
</script></body></html>"""
    (destination / "review_map.html").write_text(html, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="Candidate GeoPackage")
    parser.add_argument("--output", default="outputs/review")
    parser.add_argument("--sample-size", type=int, default=30)
    parser.add_argument("--seed", type=int, default=20260912)
    args = parser.parse_args()
    frame = gpd.read_file(args.input)
    write_review_bundle(
        frame,
        args.output,
        args.sample_size,
        args.seed,
        os.getenv("LINZ_BASEMAP_API_KEY"),
    )


if __name__ == "__main__":
    main()
