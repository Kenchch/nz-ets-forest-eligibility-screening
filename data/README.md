# Data inputs

The committed `data/processed/` GeoPackages are the fixed inputs used by
`scripts/reproduce.py`. SHA-256 values are pinned in `checksums.sha256`; the workflow
does not silently rebuild them from memory.

| Input | Publisher and service | Processing and screening use |
|---|---|---|
| Gisborne boundary | [Stats NZ Territorial Authority 2026](https://services2.arcgis.com/vKb0s8tBIA3bdocZ/arcgis/rest/services/Territorial_Authority_2026/FeatureServer/0) | Select Gisborne District and clip every source layer. |
| LCDB v6.0 | [Manaaki Whenua metadata](https://lris.scinfo.org.nz/layer/123148-lcdb-v60-land-cover-database-version-60-mainland-new-zealand/); [authoritative ArcGIS mirror](https://services.arcgis.com/XTtANUDT8Va4DLwI/arcgis/rest/services/New_Zealand_Land_Cover/FeatureServer/0) | The public mirror identifies Manaaki Whenua as source and serves 15 m simplified geometry. Selected plantable proxy classes plus explicit negative-control classes become 5,748 candidates. This is land cover, not cadastral ownership. |
| LUCAS LUM 2020 v005 | [MfE FeatureServer](https://arcgis.mfe.govt.nz/server1/rest/services/Unrestricted/MfE_LUCAS_LUM_NZ_Mainland_2020_v005_feature/FeatureServer/0) | 1989/2007 planted-forest classes provide partial historic-land-use evidence. They do not determine pre-1990 status. |
| Public conservation land | [DOC FeatureServer](https://services1.arcgis.com/3JjYDyG3oajxU6HO/arcgis/rest/services/DOC_Public_Conservation_Land/FeatureServer/0) | Project triage exclusion only; conservation tenure is not a statutory ETS eligibility rule. |
| 2024 imagery | [Gisborne District Council tile service](https://tiles.arcgis.com/tiles/8G10QCd84QpdcTJ9/arcgis/rest/services/Imagery_satellite_gisborne_2024/MapServer) (service attribution: LINZ) | Fixed 30-feature visual-review cards. Not used by automated rules. |

## Build contract

Run `python scripts/download_gisborne_data.py` to query the public ArcGIS REST
services, cache raw responses under ignored `data/raw/`, repair invalid source
topology, clip to the official boundary, explode multipart candidates, assign
stable `parcel_id` values, reproject to `EPSG:2193`, and write the four processed
GeoPackages. Rerun `python scripts/verify_checksums.py` before screening.

Source-provider metadata and licence terms remain authoritative. The 15 m LCDB
simplification limits boundary precision, and LUCAS/DOC overlays are evidence
layers rather than legal conclusions.

## Demonstration fixtures

`data/sample/` retains 12 invented NZTM geometries only for fast unit tests. They
do not feed the Gisborne findings or committed real-data outputs.
