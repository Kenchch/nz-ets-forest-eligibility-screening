# Verified rule sources

Checked on 12 September 2026. Links point to the source publisher rather than a secondary summary.

## Statutory definitions

- [Climate Change Response Act 2002, section 4 definitions](https://www.legislation.govt.nz/act/public/2002/40/en/latest/sections/DLM158592/), current consolidation checked on 12 September 2026. `Forest land`, `forest species`, `post-1989 forest land`, and `pre-1990 forest land` are all definitions within section 4. Earlier repository links used separate `LMS282060` and `DLM158592` anchors inside this same interpretation section; the register now uses one canonical current URL to avoid implying that they were separate sections.

## MPI operational guidance

- [How forest land is defined in the ETS](https://www.mpi.govt.nz/forestry/forestry-in-the-emissions-trading-scheme/about-forestry-in-the-emissions-trading-scheme-ets/how-forest-land-is-defined-in-the-ets) summarises the four size, species and cover conditions and distinguishes forest definition from historic-status eligibility.
- [Registering areas less than 30 metres wide on average](https://www.mpi.govt.nz/dmsdocument/71887/direct) describes the operational average-width method: identify the longest path, draw its centre line, take perpendicular widths at 20 metre intervals, and average them. The two algorithms in this repository are screening diagnostics, not this formal measurement.
- [How to map forestry for the ETS](https://www.mpi.govt.nz/forestry/forestry-in-the-emissions-trading-scheme/mapping-and-managing-forest-land-in-the-ets/how-to-map-forestry-for-the-emissions-trading-scheme) requires NZTM2000 or Chatham Islands Transverse Mercator 2000, closed polygons, no multipart polygons, and mapping that excludes ineligible land.
- [Geospatial Mapping Information Standard, 31 October 2025](https://www.mpi.govt.nz/dmsdocument/4756/direct) is the authoritative MPI standard for submitted mapping information.
- [Making sure mapped land is eligible](https://www.mpi.govt.nz/forestry/forestry-in-the-emissions-trading-scheme/mapping-and-managing-forest-land-in-the-ets/making-sure-mapped-land-is-eligible-for-the-emissions-trading-scheme) explains why historic imagery, applicant evidence, ownership or registered rights, species and land history remain assessor tasks.

## Open-data and basemap documentation

- [LCDB v6.0](https://lris.scinfo.org.nz/layer/123148-lcdb-v60-land-cover-database-version-60-mainland-new-zealand/) is the current land-cover source identified during research. The original project plan named v5.0; the data instructions use v6.0 and require the downloaded layer metadata and licence to be retained.
- [LUCAS NZ Land Use Map 2020 v005](https://data.mfe.govt.nz/layer/117733-lucas-nz-land-use-map-2020-v005/) supplies nominal 1989, 2007, 2012, 2016 and 2020 land-use classes. This project uses 1989/2007 planted-forest polygons as mapped evidence only.
- [Territorial Authority 2026](https://datafinder.stats.govt.nz/layer/123497-territorial-authority-2026/) is the definitive Stats NZ district boundary source used to clip Gisborne.
- [DOC Public Conservation Land](https://services1.arcgis.com/3JjYDyG3oajxU6HO/arcgis/rest/services/DOC_Public_Conservation_Land/FeatureServer/0) is streamed from DOC's public ArcGIS organisation.
- [LINZ Basemaps technical documentation](https://basemaps.linz.govt.nz/docs/user-guide/technical-documentation/) documents aerial WMTS/XYZ access in NZTM2000 and Web Mercator and the required attribution.

## Interpretation decisions

R-04 and R-05 are project triage policies, not statutory eligibility rules. Public conservation land is not automatically legally ineligible, and an LCDB class cannot establish plantability, species, future height or future crown cover. Their results therefore prioritise or remove cases from this specific opportunity-screening queue; they do not decide ETS eligibility.
