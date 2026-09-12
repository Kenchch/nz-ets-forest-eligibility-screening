# Verified rule sources

Checked on 12 September 2026. Links point to the source publisher rather than a secondary summary.

## Statutory definitions

- [Climate Change Response Act 2002, section 4 definitions](https://legislation.govt.nz/act/public/2002/0040/latest/LMS282060.html), version as at 1 January 2026. The definition of `forest land` supplies the one-hectare, crown-cover and average-width requirements. The definition of `forest species` supplies the mature-height requirement and excludes species managed primarily for fruit or nut crops.
- [Definition of pre-1990 forest land](https://www.legislation.govt.nz/act/public/2002/0040/latest/DLM158592.html). This is the historic-status boundary that the project can only proxy with a supplied evidence layer.

## MPI operational guidance

- [How forest land is defined in the ETS](https://www.mpi.govt.nz/forestry/forestry-in-the-emissions-trading-scheme/about-forestry-in-the-emissions-trading-scheme-ets/how-forest-land-is-defined-in-the-ets) summarises the four size, species and cover conditions and distinguishes forest definition from historic-status eligibility.
- [Registering areas less than 30 metres wide on average](https://www.mpi.govt.nz/dmsdocument/71887/direct) describes the operational average-width method: identify the longest path, draw its centre line, take perpendicular widths at 20 metre intervals, and average them. The two algorithms in this repository are screening diagnostics, not this formal measurement.
- [How to map forestry for the ETS](https://www.mpi.govt.nz/forestry/forestry-in-the-emissions-trading-scheme/mapping-and-managing-forest-land-in-the-ets/how-to-map-forestry-for-the-emissions-trading-scheme) requires NZTM2000 or Chatham Islands Transverse Mercator 2000, closed polygons, no multipart polygons, and mapping that excludes ineligible land.
- [Geospatial Mapping Information Standard, 31 October 2025](https://www.mpi.govt.nz/dmsdocument/4756/direct) is the authoritative MPI standard for submitted mapping information.
- [Making sure mapped land is eligible](https://www.mpi.govt.nz/forestry/forestry-in-the-emissions-trading-scheme/mapping-and-managing-forest-land-in-the-ets/making-sure-mapped-land-is-eligible-for-the-emissions-trading-scheme) explains why historic imagery, applicant evidence, ownership or registered rights, species and land history remain assessor tasks.

## Open-data and basemap documentation

- [LCDB v6.0](https://lris.scinfo.org.nz/layer/123148-lcdb-v60-land-cover-database-version-60-mainland-new-zealand/) is the current land-cover source identified during research. The original project plan named v5.0; the data instructions use v6.0 and require the downloaded layer metadata and licence to be retained.
- [LINZ Basemaps technical documentation](https://basemaps.linz.govt.nz/docs/user-guide/technical-documentation/) documents aerial WMTS/XYZ access in NZTM2000 and Web Mercator and the required attribution.

## Interpretation decisions

R-04 and R-05 are project triage policies, not statutory eligibility rules. Public conservation land is not automatically legally ineligible, and an LCDB class cannot establish plantability, species, future height or future crown cover. Their results therefore prioritise or remove cases from this specific opportunity-screening queue; they do not decide ETS eligibility.

