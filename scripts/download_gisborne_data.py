"""Download and prepare the pinned Gisborne open-data study inputs.

The script uses public ArcGIS REST endpoints so no portal API token is needed.
Large nationwide layers are queried by the Gisborne bounding box, downloaded in
object-id batches, then clipped to the official 2026 district boundary locally.
"""

from __future__ import annotations

import hashlib
import json
import urllib.parse
import urllib.request
from pathlib import Path

import geopandas as gpd
import pandas as pd

from ets_screening.io_utils import normalise_gpkg


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"

BOUNDARY_URL = (
    "https://services2.arcgis.com/vKb0s8tBIA3bdocZ/arcgis/rest/services/"
    "Territorial_Authority_2026/FeatureServer/0"
)
LCDB_URL = (
    "https://services.arcgis.com/XTtANUDT8Va4DLwI/arcgis/rest/services/"
    "New_Zealand_Land_Cover/FeatureServer/0"
)
LUCAS_URL = (
    "https://arcgis.mfe.govt.nz/server1/rest/services/Unrestricted/"
    "MfE_LUCAS_LUM_NZ_Mainland_2020_v005_feature/FeatureServer/0"
)
DOC_URL = (
    "https://services1.arcgis.com/3JjYDyG3oajxU6HO/arcgis/rest/services/"
    "DOC_Public_Conservation_Land/FeatureServer/0"
)

PLANTABLE_CLASSES = {
    "High Producing Exotic Grassland",
    "Low Producing Grassland",
    "Gorse and/or Broom",
    "Mixed Exotic Shrubland",
    "Bare or Lightly Vegetated Surfaces",
}

# Deliberately include obvious negative controls so R-05 is exercised on real
# observations instead of being made tautological by preprocessing.
NON_PLANTABLE_CONTROL_CLASSES = {
    "Built-up Area (settlement)",
    "Estuarine Open Water",
    "Gravel and Rock",
    "Lake or Pond",
    "Not land",
    "Permanent Snow and Ice",
    "River",
    "Sand and Gravel",
    "Surface Mine or Dump",
    "Transport Infrastructure",
    "Urban Parkland/Open Space",
}
CANDIDATE_SOURCE_CLASSES = PLANTABLE_CLASSES | NON_PLANTABLE_CONTROL_CLASSES
MINIMUM_FRAGMENT_AREA_M2 = 1.0


def _request_json(url: str, params: dict[str, object], *, post: bool = False) -> dict:
    encoded = urllib.parse.urlencode(params).encode("utf-8")
    request = urllib.request.Request(
        url if post else f"{url}?{encoded.decode('utf-8')}",
        data=encoded if post else None,
        headers={"User-Agent": "nz-ets-screening/0.2"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        payload = json.load(response)
    if "error" in payload:
        raise RuntimeError(f"ArcGIS REST error from {url}: {payload['error']}")
    return payload


def _query_geojson(service: str, params: dict[str, object]) -> gpd.GeoDataFrame:
    payload = _request_json(
        f"{service}/query",
        {**params, "f": "geojson", "outSR": 2193, "returnGeometry": "true"},
        post=True,
    )
    return gpd.GeoDataFrame.from_features(payload["features"], crs="EPSG:2193")


def _download_by_bbox(
    service: str,
    bbox: tuple[float, float, float, float],
    fields: str,
    *,
    batch_size: int = 500,
    where: str = "1=1",
) -> gpd.GeoDataFrame:
    geometry = ",".join(f"{value:.3f}" for value in bbox)
    common = {
        "where": where,
        "geometry": geometry,
        "geometryType": "esriGeometryEnvelope",
        "inSR": 2193,
        "spatialRel": "esriSpatialRelIntersects",
    }
    id_payload = _request_json(
        f"{service}/query",
        {**common, "f": "json", "returnIdsOnly": "true"},
        post=True,
    )
    object_ids = sorted(id_payload.get("objectIds") or [])
    frames: list[gpd.GeoDataFrame] = []
    for start in range(0, len(object_ids), batch_size):
        ids = object_ids[start : start + batch_size]
        frames.append(
            _query_geojson(
                service,
                {
                    "objectIds": ",".join(map(str, ids)),
                    "outFields": fields,
                },
            )
        )
        print(f"{service.rsplit('/', 1)[0].rsplit('/', 1)[-1]}: {min(start + batch_size, len(object_ids))}/{len(object_ids)}")
    if not frames:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:2193")
    return gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs="EPSG:2193")


def _clip(frame: gpd.GeoDataFrame, boundary: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    frame = frame.copy()
    frame.geometry = frame.geometry.make_valid()
    mask = boundary.geometry.iloc[0]
    if not mask.is_valid:
        mask = mask.make_valid()
    clipped = gpd.clip(frame, mask, keep_geom_type=True)
    return clipped.explode(index_parts=False, ignore_index=True)


def _cached_download(
    name: str,
    service: str,
    bbox: tuple[float, float, float, float],
    fields: str,
    *,
    batch_size: int = 500,
    where: str = "1=1",
) -> gpd.GeoDataFrame:
    path = RAW / f"{name}.gpkg"
    if path.exists():
        print(f"{name}: reading cached {path}")
        return gpd.read_file(path)
    frame = _download_by_bbox(
        service, bbox, fields, batch_size=batch_size, where=where
    )
    frame.to_file(path, layer=name, driver="GPKG")
    return frame


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    PROCESSED.mkdir(parents=True, exist_ok=True)

    boundary_path = RAW / "gisborne_boundary.geojson"
    if boundary_path.exists():
        boundary = gpd.read_file(boundary_path)
    else:
        boundary = _query_geojson(
            BOUNDARY_URL,
            {
                "where": "TA2026_V1_00_NAME='Gisborne District'",
                "outFields": "TA2026_V1_00,TA2026_V1_00_NAME,LAND_AREA_SQ_KM",
            },
        )
    if len(boundary) != 1:
        raise RuntimeError(f"expected one Gisborne boundary, received {len(boundary)}")
    boundary.to_file(boundary_path, driver="GeoJSON")
    bbox = tuple(boundary.total_bounds)

    lcdb = _cached_download(
        "lcdb_v60_screening_bbox",
        LCDB_URL,
        bbox,
        "OBJECTID,LCDB_UID,Name_2023,Class_2023",
        where="Name_2023 IN ("
        + ",".join(f"'{name}'" for name in sorted(CANDIDATE_SOURCE_CLASSES))
        + ")",
    )
    lucas = _cached_download(
        "lucas_v005_bbox",
        LUCAS_URL,
        bbox,
        "OBJECTID,LUCID_1989,LUCID_2007,LUCID_2020,START_1989,START_2007",
        where="LUCID_1989 LIKE '72%' AND LUCID_2007 LIKE '72%'",
    )
    conservation = _cached_download(
        "doc_conservation_bbox",
        DOC_URL,
        bbox,
        "OBJECTID,NaPALIS_ID,Type,Name,Legislation,Section",
    )

    candidates = _clip(lcdb, boundary)
    candidates = candidates[candidates["Name_2023"].isin(CANDIDATE_SOURCE_CLASSES)].copy()
    fragment_count = int((candidates.geometry.area < MINIMUM_FRAGMENT_AREA_M2).sum())
    candidates = candidates[candidates.geometry.area >= MINIMUM_FRAGMENT_AREA_M2].copy()
    candidates = candidates.sort_values("LCDB_UID").reset_index(drop=True)
    part = candidates.groupby("LCDB_UID").cumcount() + 1
    total_parts = candidates.groupby("LCDB_UID")["LCDB_UID"].transform("size")
    candidates["unit_id"] = candidates["LCDB_UID"].astype(str)
    candidates.loc[total_parts > 1, "unit_id"] += "-part-" + part.astype(str)
    candidates["lcdb_class"] = candidates["Name_2023"]
    candidates = candidates[["unit_id", "lcdb_class", "geometry"]].sort_values("unit_id")

    # This is mapped evidence only: the Act's complete pre-1990 definition also
    # requires land-history and liability facts that LUCAS cannot establish.
    pre1990 = _clip(lucas, boundary)
    pre1990 = pre1990[
        pre1990["LUCID_1989"].astype(str).str.startswith("72")
        & pre1990["LUCID_2007"].astype(str).str.startswith("72")
    ].copy()
    conservation = _clip(conservation, boundary)

    outputs = {
        "gisborne_boundary.gpkg": boundary,
        "gisborne_candidates.gpkg": candidates,
        "gisborne_pre1990_evidence.gpkg": pre1990,
        "gisborne_conservation.gpkg": conservation,
    }
    for filename, frame in outputs.items():
        path = PROCESSED / filename
        if path.exists():
            path.unlink()
        frame.to_file(path, layer=path.stem, driver="GPKG")
        normalise_gpkg(path)

    manifest = {
        "study_area": "Gisborne District",
        "crs": "EPSG:2193",
        "feature_counts": {name: len(frame) for name, frame in outputs.items()},
        "discarded_clip_fragments_below_1_m2": fragment_count,
        "sha256": {name: _sha256(PROCESSED / name) for name in outputs},
        "sources": {
            "boundary": BOUNDARY_URL,
            "lcdb": LCDB_URL,
            "lucas": LUCAS_URL,
            "conservation": DOC_URL,
        },
        "lcdb_geometry_note": "ArcGIS Living Atlas mirror is simplified at 15 m; source is LCDB v6.0.",
    }
    (PROCESSED / "gisborne_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
