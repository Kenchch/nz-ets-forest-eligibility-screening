"""Create a fixed-seed review queue with offline map controls and online imagery."""

from __future__ import annotations

import argparse
import base64
from hashlib import sha256
import json
from numbers import Integral
from pathlib import Path
import shutil
import tempfile
import warnings

import geopandas as gpd
import pandas as pd

from .load import InputValidationError, assert_nztm2000, read_layer
from .io_utils import PublicationRecoveryError, normalise_gpkg, publish_outputs
from .review_labels import (
    LABEL_VOCABULARY,
    REVIEW_COLUMNS,
    load_review_labels,
    load_review_sample_ids,
    validate_review_sample_ids,
)

DEFAULT_REVIEW_SIZE = 30
DEFAULT_REVIEW_SEED = 20260912
#: Properties published into the review map. Everything else stays out of the
#: HTML, so an unexpected input column cannot reach the page.
MAP_FIELDS = ("unit_id", "lcdb_class", "area_ha", "status")
#: About 1 cm at New Zealand latitudes; enough for review, and stable across
#: PROJ versions that differ in the last digits.
MAP_COORDINATE_DECIMALS = 7
MAP_SCOPE = "Screening / triage only - not an ETS eligibility determination."

LINZ_ATTRIBUTION = (
    'LINZ CC BY 4.0 © Imagery Basemap contributors - '
    'https://www.linz.govt.nz/data/linz-data/linz-basemaps/data-attribution'
)

# Leaflet is vendored rather than loaded from a CDN so the review map opens on
# an air-gapped or proxy-restricted assessor workstation.
VENDOR = Path(__file__).resolve().parent / "vendor" / "leaflet-1.9.4"
LEAFLET_ATTRIBUTION = (
    "Leaflet 1.9.4, BSD-2-Clause, (c) 2010-2023 Volodymyr Agafonkin - "
    "bundled offline from https://leafletjs.com"
)


def select_review_sample(
    candidates: gpd.GeoDataFrame,
    sample_size: int = DEFAULT_REVIEW_SIZE,
    seed: int = DEFAULT_REVIEW_SEED,
    sample_ids: list[str] | None = None,
) -> gpd.GeoDataFrame:
    assert_nztm2000(candidates, "review candidates")
    if not isinstance(sample_size, Integral) or isinstance(sample_size, bool) or sample_size < 0:
        raise ValueError("sample_size must be a non-negative integer")
    if "unit_id" not in candidates:
        raise ValueError("review candidates require unit_id")
    candidates = candidates.copy()
    candidates["unit_id"] = validate_review_sample_ids(candidates["unit_id"].tolist())
    if sample_ids is not None:
        sample_ids = validate_review_sample_ids(sample_ids)
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
        .reset_index(drop=True)
    )


def _round_coordinates(value: object, decimals: int) -> object:
    """Round GeoJSON coordinates so PROJ last-digit noise cannot drift the page."""

    if isinstance(value, dict):
        return {
            key: _round_coordinates(item, decimals) if key in ("coordinates", "geometry", "features") else item
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_round_coordinates(item, decimals) for item in value]
    if isinstance(value, float):
        return round(value, decimals)
    return value


def _csp_hash(script: str) -> str:
    digest = base64.b64encode(sha256(script.encode("utf-8")).digest()).decode("ascii")
    return f"'sha256-{digest}'"


def _script_json(value: object) -> str:
    # JSON string escaping alone does not prevent the HTML parser from closing
    # a script element when an input attribute contains </script>.
    return json.dumps(value).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def write_review_bundle(
    candidates: gpd.GeoDataFrame,
    destination: str | Path,
    sample_size: int = DEFAULT_REVIEW_SIZE,
    seed: int = DEFAULT_REVIEW_SEED,
    api_key: str | None = None,
    sample_ids: list[str] | None = None,
) -> None:
    destination = Path(destination)
    sample = select_review_sample(candidates, sample_size, seed, sample_ids)
    existing_labels = destination / "review_labels.csv"
    if existing_labels.exists():
        load_review_labels(existing_labels, sample["unit_id"].tolist())
    cards = destination / "cards"
    if cards.exists() and any(cards.iterdir()):
        old_ids = load_review_sample_ids(destination / "review_sample_ids.csv")
        if set(old_ids) != set(sample["unit_id"]):
            raise ValueError(
                "review sample changed while imagery cards are present; "
                "use the pinned review_sample_ids or a separate output directory"
            )

    # Only the fields an assessor needs reach the page. Extra candidate
    # columns, such as applicant notes, stay in the GeoPackage.
    public = [column for column in MAP_FIELDS if column in sample.columns]
    geojson = _round_coordinates(
        json.loads(sample[[*public, "geometry"]].to_crs(4326).to_json(drop_id=True)),
        MAP_COORDINATE_DECIMALS,
    )
    if api_key:
        warnings.warn(
            "API keys are no longer embedded in review artifacts; enter the key in the map's imagery control.",
            UserWarning,
            stacklevel=2,
        )
    tile_url = (
        "https://basemaps.linz.govt.nz/v1/tiles/aerial/WebMercatorQuad/"
        "{z}/{x}/{y}.webp"
    )
    leaflet_css = (VENDOR / "leaflet.css").read_text(encoding="utf-8")
    leaflet_js = (VENDOR / "leaflet.js").read_text(encoding="utf-8")
    labels = " / ".join(LABEL_VOCABULARY)
    app_js = f"""
const features={_script_json(geojson)};
const map=L.map('map');
L.control.scale({{imperial:false}}).addTo(map);
const tileUrl={_script_json(tile_url)};
let imageryLayer=null;
const layer=L.geoJSON(features,{{style:{{color:'#ff2d55',weight:3,fillOpacity:0.08}},
 onEachFeature:(f,l)=>{{const popup=document.createElement('div');
 const title=document.createElement('b');title.textContent=String(f.properties.unit_id);
 popup.append(title);
 for(const [name,label] of [['lcdb_class','LCDB class'],['area_ha','Area (ha)'],['status','Status']]){{
  if(f.properties[name]===undefined||f.properties[name]===null)continue;
  const line=document.createElement('div');line.textContent=label+': '+String(f.properties[name]);popup.append(line);
 }}
 l.bindPopup(popup);}}}}).addTo(map);
if(layer.getBounds().isValid()){{map.fitBounds(layer.getBounds().pad(0.2));}}
else{{map.setView([-40.9,174.9],5);}}
const instructions=L.control({{position:'topright'}});
instructions.onAdd=function(){{const d=L.DomUtil.create('div','note');
const scope=document.createElement('b');scope.textContent={_script_json(MAP_SCOPE)};
const body=document.createElement('p');
body.textContent=features.features.length ?
 'Human review queue: red outlines are sampled candidate units. Inspect the imagery and assign one label: {labels}. Record your own name, the date and what you actually saw. Review must be completed by a named person.' :
 'No candidate polygons in this review sample.';
d.append(scope,body);
return d;}};
instructions.addTo(map);
const imageryControl=L.control({{position:'bottomleft'}});
imageryControl.onAdd=function(){{
 const form=L.DomUtil.create('form','note');
 const description=document.createElement('p');
 description.textContent='LINZ aerial imagery requires an internet connection and an API key. The key stays in this page session and is sent only to LINZ.';
 const label=document.createElement('label');label.textContent='LINZ API key ';
 const input=document.createElement('input');input.type='password';input.autocomplete='off';
 label.append(input);
 const button=document.createElement('button');button.type='submit';button.textContent='Load imagery';
 form.append(description,label,button);
 L.DomEvent.disableClickPropagation(form);L.DomEvent.disableScrollPropagation(form);
 form.addEventListener('submit',event=>{{event.preventDefault();
  const key=input.value.trim();if(!key)return;
  if(imageryLayer)map.removeLayer(imageryLayer);
  imageryLayer=L.tileLayer(tileUrl+'?api='+encodeURIComponent(key),
   {{attribution:{_script_json(LINZ_ATTRIBUTION)},maxZoom:22,referrerPolicy:'no-referrer'}}).addTo(map);
  input.value='';
 }});
 return form;
}};
imageryControl.addTo(map);
"""
    # Inline scripts are allowed only by hash, and the page may load images
    # from LINZ and nowhere else, so injected markup can neither run nor
    # send data out.
    csp = "; ".join(
        [
            "default-src 'none'",
            f"script-src {_csp_hash(leaflet_js)} {_csp_hash(app_js)}",
            "style-src 'unsafe-inline'",
            "img-src https://basemaps.linz.govt.nz data:",
            "base-uri 'none'",
            "form-action 'none'",
        ]
    )
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{csp}">
<title>ETS screening review queue (triage only)</title>
<!-- {LEAFLET_ATTRIBUTION} -->
<style>{leaflet_css}</style>
<style>html,body,#map{{height:100%;margin:0}} .note{{background:white;padding:8px;max-width:26em}}</style></head>
<body><div id="map"></div><script>{leaflet_js}</script>
<script>{app_js}</script></body></html>"""
    # Build the complete bundle before replacing existing evidence. A failed
    # GeoPackage write or missing vendor asset must not truncate the old queue.
    destination.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".review-build-", dir=destination))
    retain_stage = False
    try:
        sample.to_file(stage / "review_queue.gpkg", layer="review_queue", driver="GPKG", index=False)
        normalise_gpkg(stage / "review_queue.gpkg")
        sample[["unit_id"]].to_csv(stage / "review_sample_ids.csv", index=False, lineterminator="\n")
        template = pd.DataFrame({column: "" for column in REVIEW_COLUMNS}, index=sample.index)
        template["unit_id"] = sample["unit_id"].to_numpy()
        template.to_csv(stage / "review_labels_template.csv", index=False, lineterminator="\n")
        (stage / "review_map.html").write_text(html, encoding="utf-8", newline="\n")
        publish_outputs(stage, destination)
    except PublicationRecoveryError:
        retain_stage = True
        raise
    finally:
        if not retain_stage:
            shutil.rmtree(stage, ignore_errors=True)


def _non_negative_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"not an integer: {text!r}") from error
    if value < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return value


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="Candidate GeoPackage, such as candidates.gpkg from ets-screen")
    parser.add_argument("--output", default="outputs/review")
    parser.add_argument("--sample-size", type=_non_negative_int, default=DEFAULT_REVIEW_SIZE)
    parser.add_argument("--seed", type=int, default=DEFAULT_REVIEW_SEED)
    args = parser.parse_args(argv)
    try:
        frame = read_layer(args.input, ("unit_id",), "review candidates")
    except InputValidationError as error:
        parser.exit(3, f"{parser.prog}: input validation failed: {error}\n")
    if "status" in frame.columns and frame["status"].ne("candidate_review").any():
        parser.exit(
            3,
            f"{parser.prog}: input contains units whose status is not candidate_review; "
            "pass candidates.gpkg, not quarantine.gpkg\n",
        )
    write_review_bundle(frame, args.output, args.sample_size, args.seed)


if __name__ == "__main__":
    main()
