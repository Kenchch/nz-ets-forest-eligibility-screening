# Data inputs

The committed `data/processed/` GeoPackages are the fixed inputs used by
`scripts/reproduce.py`. SHA-256 values are pinned in `checksums.sha256`; the workflow
does not silently rebuild them from memory.

| Input | Publisher and service | Processing and screening use |
|---|---|---|
| Gisborne boundary | [Stats NZ Territorial Authority 2026](https://services2.arcgis.com/vKb0s8tBIA3bdocZ/arcgis/rest/services/Territorial_Authority_2026/FeatureServer/0) (CC BY 4.0; attribution: Stats NZ – Tatauranga Aotearoa; [publisher licence metadata](https://www.arcgis.com/sharing/rest/content/items/b7f8726da7f6467a9cb42221b0013938?f=pjson)) | Select Gisborne District and clip every source layer. |
| LCDB v6.0 | [Manaaki Whenua / Landcare Research, LRIS layer 123148](https://lris.scinfo.org.nz/layer/123148-lcdb-v60-land-cover-database-version-60-mainland-new-zealand/) (CC BY 4.0, [doi:10.26060/WM99-RY32](https://doi.org/10.26060/WM99-RY32), added 2 Oct 2025, updated 21 Oct 2025); [public ArcGIS Living Atlas mirror, simplified at 15 m](https://services.arcgis.com/XTtANUDT8Va4DLwI/arcgis/rest/services/New_Zealand_Land_Cover/FeatureServer/0) | Classified by `Name_2023` (the 2023/24 time step; v6.0 fields are suffixed `_2023`, not `_2024`) and keyed by `LCDB_UID`. The public mirror identifies Manaaki Whenua as source and serves 15 m simplified geometry. Selected proxy classes plus explicit negative controls become 5,712 land-cover mapping units after sliver filtering. They are not cadastral parcels or ETS application areas. |
| LUCAS LUM 2020 v005 | [MfE FeatureServer](https://arcgis.mfe.govt.nz/server1/rest/services/Unrestricted/MfE_LUCAS_LUM_NZ_Mainland_2020_v005_feature/FeatureServer/0) (CC BY 4.0 by Ministry for the Environment; metadata also credits Manaaki Whenua – Landcare Research; [publisher licence metadata](https://www.arcgis.com/sharing/rest/content/items/c13b3563d0d246ac978a5da1be3c921d?f=pjson)) | Polygons whose 1989 and 2007 classes are both 72 (planted forest, pre-1990) provide partial historic-land-use evidence. They do not determine pre-1990 status. **Known gap:** class 71 (natural forest in 1989) is not in the committed layer, although such land also cannot be post-1989 forest land under para (a)(i); see the README limitations. |
| Public conservation land | [DOC FeatureServer](https://services1.arcgis.com/3JjYDyG3oajxU6HO/arcgis/rest/services/DOC_Public_Conservation_Land/FeatureServer/0) (CC BY 4.0; attribution: Department of Conservation, © Crown; [publisher licence metadata](https://www.arcgis.com/sharing/rest/content/items/72354ba9bf7a4706af3fdfe60f86eea1?f=pjson)) | Project triage exclusion only; conservation tenure is not a statutory ETS eligibility rule. |
| 2024 imagery | [Gisborne District Council tile service](https://tiles.arcgis.com/tiles/8G10QCd84QpdcTJ9/arcgis/rest/services/Imagery_satellite_gisborne_2024/MapServer) (service attribution: LINZ) | Fixed 30-feature visual-review cards. Not used by automated rules. The tile grid is 1.32 m per pixel at the level used, but the native imagery resolution appears much coarser; the card renderer records the service's own credit in `cards/SOURCE.json` when cards are next rendered. |

## Verified licence evidence

The three licences above were checked on 2026-09-23 against the `licenseInfo`
fields of the official ArcGIS items linked by each downloaded service's
`serviceItemId`, rather than inferred from a publisher's general website policy.
[license_metadata.json](license_metadata.json) preserves the item IDs, owners,
service URLs, attribution and licence statements retrieved on that date.
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) applies to those source
layers; the project's MIT code licence does not replace their data terms.
The distributed study layers are modified extracts: they are clipped to Gisborne,
repaired and, where applicable, exploded/filtered as described below. Preserve
the source attribution, licence link and this description of changes when
redistributing them. These checks do not establish new terms for the imagery.

## Build contract

Run `python scripts/download_gisborne_data.py` to query the public ArcGIS REST
services with geometry requested in `EPSG:2193` (`outSR=2193`; nothing is
reprojected locally), cache raw responses under ignored `data/raw/`, repair
invalid source topology, clip to the official boundary, explode multipart
mapping units, remove 36 numerical clipping fragments below 1 m², number each
part of a multipart unit by its own geometry (largest first) so its
`-part-N` ID does not depend on row order, and write the four processed
GeoPackages. Rerun `python scripts/verify_checksums.py` before screening.

Downloads are checked for completeness batch by batch, retried on transient
server errors, and sized to the service's `maxRecordCount`. Each raw cache has a
`.query.json` sidecar recording the query, the service version and edit date,
the retrieval time, the feature count and the raw file's SHA-256; a cache is
reused only for an identical query. The next refresh writes those records into
`gisborne_manifest.json` under `source_queries`.

### Provenance limits of the committed inputs

The committed processed files predate those records. Their upstream services
are live and mutable, the raw downloads were not archived, and GeoPackage bytes
also vary with the GDAL version that writes them. `checksums.sha256` therefore
proves only that these are the files the results were computed from; it cannot
show that a fresh download would reproduce them. Archiving the raw responses
with a DOI (for example on Zenodo), or switching to the versioned LRIS LCDB
export, is the remaining step to close that gap.

Source-provider metadata and licence terms remain authoritative. The 15 m LCDB
simplification limits boundary precision, and LUCAS/DOC overlays are evidence
layers rather than legal conclusions.

## Demonstration fixtures

`data/sample/` holds the invented NZTM fixtures written by
`python -m ets_screening.demo_data`: 12 candidate polygons plus one pre-1990 and
one conservation polygon. They are for trying the CLI on files; the unit tests
build the same shapes in memory with `build_demo_layers()`. They do not feed the
Gisborne findings or committed real-data outputs.
