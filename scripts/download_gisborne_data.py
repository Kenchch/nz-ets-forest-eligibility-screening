"""Download and prepare the pinned Gisborne open-data study inputs.

The script uses public ArcGIS REST endpoints so no portal API token is needed.
Large nationwide layers are queried by the Gisborne bounding box, downloaded in
object-id batches, then clipped to the official 2026 district boundary locally.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import shutil
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely import make_valid

from ets_screening.io_utils import PublicationRecoveryError, normalise_gpkg, publish_outputs


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


class IncompleteQueryError(RuntimeError):
    """An ArcGIS feature response was truncated by its transfer limit."""


#: A misbehaving or hijacked endpoint should not be able to exhaust memory
#: before the payload is even parsed. The largest legitimate page of Gisborne
#: features is a few megabytes.
MAXIMUM_JSON_BYTES = 256 * 1024 * 1024


def _read_capped(response, limit: int, url: str) -> bytes:
    """Read a response body, refusing anything larger than `limit` bytes."""

    declared = response.headers.get("Content-Length")
    if declared is not None and declared.isdigit() and int(declared) > limit:
        raise RuntimeError(f"response from {url} declares {declared} bytes; limit is {limit}")
    body = response.read(limit + 1)
    if len(body) > limit:
        raise RuntimeError(f"response from {url} exceeds the {limit} byte limit")
    return body


#: Attempts per request. Public ArcGIS services drop connections and return
#: transient 5xx responses during long batch downloads.
REQUEST_ATTEMPTS = 4
DEFAULT_BATCH_SIZE = 500


def _open_with_retry(request: urllib.request.Request, url: str) -> bytes:
    for attempt in range(REQUEST_ATTEMPTS):
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                return _read_capped(response, MAXIMUM_JSON_BYTES, url)
        except urllib.error.HTTPError as error:
            if error.code < 500 or attempt == REQUEST_ATTEMPTS - 1:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == REQUEST_ATTEMPTS - 1:
                raise
        time.sleep(2**attempt)
    raise AssertionError("unreachable")


def _request_json(url: str, params: dict[str, object], *, post: bool = False) -> dict:
    encoded = urllib.parse.urlencode(params).encode("utf-8")
    request = urllib.request.Request(
        url if post else f"{url}?{encoded.decode('utf-8')}",
        data=encoded if post else None,
        headers={"User-Agent": "nz-ets-screening/0.2"},
    )
    payload = json.loads(_open_with_retry(request, url))
    if not isinstance(payload, dict):
        raise RuntimeError(f"invalid ArcGIS REST response from {url}: expected an object")
    if "error" in payload:
        raise RuntimeError(f"ArcGIS REST error from {url}: {payload['error']}")
    return payload


def _query_geojson(service: str, params: dict[str, object]) -> gpd.GeoDataFrame:
    payload = _request_json(
        f"{service}/query",
        {**params, "f": "geojson", "outSR": 2193, "returnGeometry": "true"},
        post=True,
    )
    if payload.get("exceededTransferLimit"):
        raise IncompleteQueryError(f"ArcGIS transfer limit exceeded for {service}")
    if not isinstance(payload.get("features"), list):
        raise RuntimeError(f"invalid ArcGIS feature response from {service}")
    if not payload["features"]:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:2193")
    return gpd.GeoDataFrame.from_features(payload["features"], crs="EPSG:2193")


def _download_by_bbox(
    service: str,
    bbox: tuple[float, float, float, float],
    fields: str,
    *,
    batch_size: int = 500,
    where: str = "1=1",
) -> gpd.GeoDataFrame:
    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size < 1:
        raise ValueError("batch_size must be a positive integer")
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
    if "objectIds" not in id_payload or id_payload.get("exceededTransferLimit"):
        raise RuntimeError(f"incomplete ArcGIS object ID response from {service}")
    object_ids = id_payload["objectIds"]
    if object_ids is None:
        object_ids = []
    if not isinstance(object_ids, list) or any(
        isinstance(value, bool) or not isinstance(value, int) for value in object_ids
    ):
        raise RuntimeError(f"invalid ArcGIS object IDs from {service}")
    if len(set(object_ids)) != len(object_ids):
        raise RuntimeError(f"duplicate ArcGIS object IDs from {service}")
    object_ids = sorted(object_ids)
    id_field = id_payload.get("objectIdFieldName")
    if object_ids and (not isinstance(id_field, str) or not id_field):
        raise RuntimeError(f"missing ArcGIS object ID field name from {service}")
    out_fields = [field.strip() for field in fields.split(",")]
    if object_ids and "*" not in out_fields and id_field not in out_fields:
        out_fields.append(id_field)

    def download_batch(ids: list[int]) -> gpd.GeoDataFrame:
        try:
            frame = _query_geojson(
                service,
                {"objectIds": ",".join(map(str, ids)), "outFields": ",".join(out_fields)},
            )
        except IncompleteQueryError:
            frame = None
        if frame is not None and not frame.empty:
            if id_field not in frame:
                raise RuntimeError(f"ArcGIS response is missing {id_field} for {service}")
            returned = frame[id_field].tolist()
            if len(set(returned)) != len(returned) or not set(returned).issubset(ids):
                raise RuntimeError(f"unexpected or duplicate ArcGIS features from {service}")
            if set(returned) == set(ids):
                return frame.sort_values(id_field).reset_index(drop=True)
        # Some servers omit exceededTransferLimit despite returning only part of
        # an ID batch. Never cache that partial response as a complete download.
        if len(ids) == 1:
            raise RuntimeError(f"ArcGIS failed to return requested object ID {ids[0]} from {service}")
        middle = len(ids) // 2
        return gpd.GeoDataFrame(
            pd.concat([download_batch(ids[:middle]), download_batch(ids[middle:])], ignore_index=True),
            crs="EPSG:2193",
        )

    frames: list[gpd.GeoDataFrame] = []
    for start in range(0, len(object_ids), batch_size):
        ids = object_ids[start : start + batch_size]
        frames.append(download_batch(ids))
        print(f"{service.rsplit('/', 1)[0].rsplit('/', 1)[-1]}: {min(start + batch_size, len(object_ids))}/{len(object_ids)}")
    if not frames:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:2193")
    return gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs="EPSG:2193")


def _clip(frame: gpd.GeoDataFrame, boundary: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    frame = frame.copy()
    frame.geometry = frame.geometry.make_valid()
    mask = boundary.geometry.iloc[0]
    if not mask.is_valid:
        mask = make_valid(mask)
    clipped = gpd.clip(frame, mask, keep_geom_type=True)
    return clipped.explode(index_parts=False, ignore_index=True)


def _service_info(service: str) -> dict[str, object]:
    """Record which version of a live service a download came from."""

    info = _request_json(service, {"f": "json"})
    editing = info.get("editingInfo") or {}
    return {
        "url": service,
        "current_version": info.get("currentVersion"),
        "service_item_id": info.get("serviceItemId"),
        "last_edit_date": editing.get("lastEditDate") or editing.get("dataLastEditDate"),
        "max_record_count": info.get("maxRecordCount"),
    }


def _batch_size(info: dict[str, object]) -> int:
    limit = info.get("max_record_count")
    if isinstance(limit, int) and not isinstance(limit, bool) and limit > 0:
        return min(DEFAULT_BATCH_SIZE, limit)
    return DEFAULT_BATCH_SIZE


def _cached_download(
    name: str,
    service: str,
    bbox: tuple[float, float, float, float],
    fields: str,
    *,
    where: str = "1=1",
) -> tuple[gpd.GeoDataFrame, dict[str, object]]:
    """Download once, and reuse the cache only for the identical query.

    The query parameters are stored beside the cache; changing the class list,
    fields or extent forces a fresh download instead of silently reusing data
    fetched for a different question.
    """

    path = RAW / f"{name}.gpkg"
    sidecar = RAW / f"{name}.query.json"
    query = {"service": service, "where": where, "fields": fields, "bbox": [round(value, 3) for value in bbox]}
    if path.exists() and sidecar.exists():
        record = json.loads(sidecar.read_text(encoding="utf-8"))
        if record.get("query") == query and record.get("raw_sha256") == _sha256(path):
            print(f"{name}: reading cached {path}")
            return gpd.read_file(path), record
        print(f"{name}: cache does not match this query; downloading again")
    info = _service_info(service)
    frame = _download_by_bbox(service, bbox, fields, batch_size=_batch_size(info), where=where)
    _write_frame_atomically(frame, path, layer=name, driver="GPKG")
    record = {
        "query": query,
        "service": info,
        "retrieved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "feature_count": len(frame),
        "raw_sha256": _sha256(path),
    }
    sidecar.write_text(json.dumps(record, indent=2), encoding="utf-8", newline="\n")
    return frame, record


def _write_frame_atomically(frame: gpd.GeoDataFrame, path: Path, **kwargs) -> None:
    """A failed GIS write must not leave a partial file that looks cached."""

    with tempfile.TemporaryDirectory(prefix=f".{path.stem}-", dir=path.parent) as temporary:
        staged_path = Path(temporary) / path.name
        frame.to_file(staged_path, **kwargs)
        staged_path.replace(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assign_unit_ids(candidates: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Give each exploded LCDB part an ID derived from its own geometry.

    Parts are numbered largest first, then by position, not by the order the
    service or clip returned them, so each -part-N ID keeps pointing at the
    same land on a refresh.
    """

    point = candidates.geometry.representative_point()
    candidates = (
        candidates.assign(
            _area=-candidates.geometry.area.round(3),
            _y=point.y.round(3),
            _x=point.x.round(3),
        )
        .sort_values(["LCDB_UID", "_area", "_y", "_x"], kind="mergesort")
        .drop(columns=["_area", "_y", "_x"])
        .reset_index(drop=True)
    )
    part = candidates.groupby("LCDB_UID").cumcount() + 1
    total_parts = candidates.groupby("LCDB_UID")["LCDB_UID"].transform("size")
    candidates["unit_id"] = candidates["LCDB_UID"].astype(str)
    candidates.loc[total_parts > 1, "unit_id"] += "-part-" + part.astype(str)
    return candidates


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
    if not boundary_path.exists():
        _write_frame_atomically(boundary, boundary_path, driver="GeoJSON")
    bbox = tuple(boundary.total_bounds)

    lcdb, lcdb_record = _cached_download(
        "lcdb_v60_screening_bbox",
        LCDB_URL,
        bbox,
        "OBJECTID,LCDB_UID,Name_2023,Class_2023",
        where="Name_2023 IN ("
        + ",".join(f"'{name}'" for name in sorted(CANDIDATE_SOURCE_CLASSES))
        + ")",
    )
    lucas, lucas_record = _cached_download(
        "lucas_v005_bbox",
        LUCAS_URL,
        bbox,
        "OBJECTID,LUCID_1989,LUCID_2007,LUCID_2020,START_1989,START_2007",
        # Known gap (audit H-04): land that was natural forest in 1989 (LUCAS
        # class 71) also fails post-1989 para (a)(i), and 71 -> 72 land can be
        # pre-1990 forest land. Widening this filter changes the committed
        # inputs, so it waits for the next deliberate data refresh.
        where="LUCID_1989 LIKE '72%' AND LUCID_2007 LIKE '72%'",
    )
    conservation, conservation_record = _cached_download(
        "doc_conservation_bbox",
        DOC_URL,
        bbox,
        "OBJECTID,NaPALIS_ID,Type,Name,Legislation,Section",
    )

    candidates = _clip(lcdb, boundary)
    candidates = candidates[candidates["Name_2023"].isin(CANDIDATE_SOURCE_CLASSES)].copy()
    fragment_count = int((candidates.geometry.area < MINIMUM_FRAGMENT_AREA_M2).sum())
    candidates = candidates[candidates.geometry.area >= MINIMUM_FRAGMENT_AREA_M2].copy()
    candidates = _assign_unit_ids(candidates)
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
    queries = {"lcdb": lcdb_record, "lucas": lucas_record, "conservation": conservation_record}
    manifest = _publish_processed(outputs, fragment_count, queries)
    print(json.dumps(manifest, indent=2))


def _publish_processed(
    outputs: dict[str, gpd.GeoDataFrame],
    fragment_count: int,
    queries: dict[str, dict[str, object]] | None = None,
) -> dict:
    """Publish a fully written input set and matching manifest, or restore it."""

    stage = Path(tempfile.mkdtemp(prefix=".gisborne-inputs-", dir=PROCESSED.parent))
    retain_stage = False
    try:
        for filename, frame in outputs.items():
            path = stage / filename
            frame.to_file(path, layer=path.stem, driver="GPKG")
            normalise_gpkg(path)
        manifest = {
        "study_area": "Gisborne District",
        "crs": "EPSG:2193",
        "feature_counts": {name: len(frame) for name, frame in outputs.items()},
        "discarded_clip_fragments_below_1_m2": fragment_count,
        "sha256": {name: _sha256(stage / name) for name in outputs},
        "sources": {
            "boundary": BOUNDARY_URL,
            "lcdb": LCDB_URL,
            "lucas": LUCAS_URL,
            "conservation": DOC_URL,
        },
        "lcdb_geometry_note": "ArcGIS Living Atlas mirror is simplified at 15 m; source is LCDB v6.0.",
        }
        if queries is not None:
            # Service versions, query text, retrieval times and raw-file hashes
            # let a later refresh tell upstream changes from local ones.
            manifest["source_queries"] = queries
        (stage / "gisborne_manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8", newline="\n"
        )
        publish_outputs(stage, PROCESSED)
        return manifest
    except PublicationRecoveryError:
        retain_stage = True
        raise
    finally:
        if not retain_stage:
            shutil.rmtree(stage)


if __name__ == "__main__":
    main()
