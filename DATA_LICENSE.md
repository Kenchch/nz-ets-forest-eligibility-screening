# Data licences and attribution

The code in this repository is MIT licensed (see [LICENSE](LICENSE)). **That
licence does not cover the data.** The processed inputs under `data/processed/`
and every derived output under `outputs/` and `arcgis/` are modified extracts of
the third-party datasets below and remain under their publishers' terms.

| Dataset | Rights holder | Licence | Version / identifier | Retrieved |
|---|---|---|---|---|
| LCDB v6.0 – Land Cover Database version 6.0, Mainland New Zealand | Manaaki Whenua – Landcare Research | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | LRIS layer 123148, [doi:10.26060/WM99-RY32](https://doi.org/10.26060/WM99-RY32); streamed from the ArcGIS Living Atlas mirror (15 m simplified) | 2026-09 |
| LUCAS NZ Land Use Map 2020 v005 | Ministry for the Environment (metadata also credits Manaaki Whenua – Landcare Research) | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | ArcGIS item `c13b3563d0d246ac978a5da1be3c921d` | 2026-09 |
| Public Conservation Land | Department of Conservation, © Crown | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | ArcGIS item `72354ba9bf7a4706af3fdfe60f86eea1` | 2026-09 |
| Territorial Authority 2026 | Stats NZ – Tatauranga Aotearoa | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | ArcGIS item `b7f8726da7f6467a9cb42221b0013938` | 2026-09 |
| Imagery Satellite Gisborne 2024 (review cards only) | Gisborne District Council; the service credits LINZ | Terms not verified by this project | Tile service `Imagery_satellite_gisborne_2024` | 2026-09 |
| LINZ Basemaps aerial (interactive review map only, loaded live) | Toitū Te Whenua LINZ and imagery contributors | [CC BY 4.0](https://www.linz.govt.nz/data/linz-data/linz-basemaps/data-attribution) | Not redistributed | at view time |

The licence statements for the four vector datasets were checked against each
service's ArcGIS item on 2026-09-23 and are preserved verbatim in
[data/license_metadata.json](data/license_metadata.json).

## Modifications

The vector data were queried by the Gisborne bounding box in EPSG:2193,
repaired (`make_valid`), clipped to the Gisborne District boundary, exploded
into single-part polygons, filtered to selected LCDB classes and to LUCAS
polygons classed as planted forest in both 1989 and 2007, and stripped of
fragments under 1 m². The outputs add screening attributes computed by this
project. None of these changes is endorsed by the rights holders.

## Suggested attribution

> Data: LCDB v6.0 © Manaaki Whenua – Landcare Research; LUCAS LUM 2020 v005 ©
> Ministry for the Environment; Public Conservation Land © Crown / Department of
> Conservation; Territorial Authority 2026 © Stats NZ. All CC BY 4.0, modified.

The imagery review cards reproduce tiles from the Gisborne District Council
service. Their redistribution terms have not been confirmed; treat the cards as
review working material and confirm the terms before republishing them.
