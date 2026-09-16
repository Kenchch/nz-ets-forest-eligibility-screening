# Verified rule sources

The statutory definitions, the MPI forest-land page, the MPI average-width
guidance and the LCDB v6.0 layer were **checked against the live publisher pages
on 16 September 2026**. Other entries were last checked on 12 September 2026 and
are marked as such. Links point to the source publisher rather than a secondary
summary.

## Statutory definitions

**Source:** [Climate Change Response Act 2002, section 4 Interpretation](https://www.legislation.govt.nz/act/public/2002/40/en/latest/sections/DLM158592/)
— single-section page on legislation.govt.nz, **Version as at 25 August 2026**.
The page also states that some amendments have not yet been incorporated, so the
consolidated text below should be re-read against the list of unincorporated
amendments before it is relied on for anything beyond screening.

All four definitions sit in **s 4(1)**. This is the only legislation URL used in
[`rule_register.csv`](rule_register.csv). The older anchor `LMS282060` was
re-opened on 16 September 2026 and resolves to the provision headed **National
adaptation plan**, not to section 4, so it is not used anywhere.

The text below is quoted verbatim. New Zealand Acts are not subject to copyright
(Copyright Act 1994, s 27).

### forest land — R-01, R-02, R-07

> **forest land**—
>
> (a) means an area of land of at least 1 hectare that has, or is likely to have,
> tree crown cover from forest species of more than 30% in each hectare; and
>
> (b) includes an area of land that temporarily does not meet the requirements
> specified in paragraph (a) because of human intervention or natural causes but
> that is likely to revert to land that meets the requirements specified in
> paragraph (a); but
>
> (c) does not include—
>
> (i) a shelter belt of forest species, where the tree crown cover has, or is
> likely to have, an average width of less than 30 metres; or
>
> (ii) an area of land where the forest species have, or are likely to have, a
> tree crown cover of an average width of less than 30 metres, unless the area is
> contiguous with land that meets the requirements specified in paragraph (a) or
> (b)

The 1 hectare minimum and the 30% crown cover are both in paragraph (a), and the
cover test is **in each hectare**, not an average over the whole area. The width
exclusion is paragraph (c), and (c)(ii) carries a contiguity exception — see
*Interpretation decisions* below.

### forest species — R-06, R-08

> **forest species** means a tree species capable of reaching at least 5 metres
> in height at maturity in the place where it is located, but does not include
> tree species grown or managed primarily for the production of fruit or nut crops

The height test is site-specific ("in the place where it is located"), and the
exclusion is for species grown or managed primarily for fruit or nut crops.

### post-1989 forest land — the screening target

> **post-1989 forest land** means forest land that—
>
> (a) is one of the following:
>
> (i) land that was not forest land on 31 December 1989:
>
> (ii) land that was forest land on 31 December 1989 but was deforested in the
> period beginning on 1 January 1990 and ending on 31 December 2007:
>
> (iii) land that was pre-1990 forest land, other than exempt land,—
>
> (A) that was deforested on or after 1 January 2008; and
>
> (B) in respect of which any liability to surrender units arising in relation to
> an activity listed in Part 1 of Schedule 3 has been satisfied:
>
> (iv) land—
>
> (A) that was pre-1990 forest land that was the subject of a P90 offset
> application; and
>
> (B) that ceased to be forest land while section 179A(1)(b) applied to it (so it
> could not be treated as deforested); and
>
> (C) in respect of which a liability to surrender units arose under section 181D
> (because the P90 offset application was declined) or section 181N(3) (because
> the land became area 1 (not offset) land),—
>
> but only if that liability has been satisfied:
>
> (v) land that was P90 offsetting land that was deforested after 1 January 2013
> and in respect of which any liability to surrender units arising in relation to
> an activity listed in Part 1A of Schedule 3 has been satisfied:
>
> (vi) land that was exempt land—
>
> (A) that has been deforested; and
>
> (B) in respect of which the number of units that would have been required to be
> surrendered in relation to an activity listed in Part 1 of Schedule 3, had the
> land not been exempt land, have been surrendered under section 182A(2):
>
> (vii) land that was exempt land that has been deforested more than 8 years ago;
> and
>
> (b) is not area 1 (approved) land (as defined in section 181) or P90 offsetting
> land

### pre-1990 forest land — R-03

> **pre-1990 forest land** means forest land that—
>
> (a) is either of the following:
>
> (i) land—
>
> (A) that was forest land on 31 December 1989; and
>
> (B) that remained as forest land on 31 December 2007 (taking into account
> subsection (5)); and
>
> (C) where the forest species on the forest land on 31 December 2007 consisted
> predominantly of exotic forest species; or
>
> (ii) land that has become pre-1990 forest land under section 181T; and
>
> (b) is not either of the following:
>
> (i) land that has been deforested and in respect of which any liability to
> surrender units arising in respect of an activity listed in Part 1 of Schedule 3
> has been satisfied; or
>
> (ii) land that was declared to be exempt land and has been deforested, and in
> respect of which the number of units that would have been required to be
> surrendered in respect of an activity listed in Part 1 of Schedule 3, had the
> land not been exempt land, have been surrendered under section 182A(2)(b)

R-03 screens for the most common route into post-1989 status, paragraph (a)(i):
land that was not forest land on 31 December 1989. Mapped 1989/2007 planted
forest overlap is evidence against that route. Routes (a)(ii)–(vii) depend on
deforestation dates, surrender liabilities and statutory status that no open
spatial layer records, and pre-1990 paragraph (a)(i)(C) depends on the species
composition on 31 December 2007, so R-03 cannot establish either status.

## MPI operational guidance

### How forest land is defined in the ETS — checked 16 September 2026

[How forest land is defined in the ETS](https://www.mpi.govt.nz/forestry/forestry-in-the-emissions-trading-scheme/about-forestry-in-the-emissions-trading-scheme-ets/how-forest-land-is-defined-in-the-ets)
restates the size, species and cover requirements in plain language. Summarised
here against the statute rather than copied:

| Requirement | MPI plain-language statement (paraphrased) | Statute, s 4(1) |
|---|---|---|
| Area | Covers at least 1 hectare | *forest land* (a) |
| Species height | Species that can reach at least 5 m when mature in that location | *forest species* |
| Crown cover | Has, or is expected to reach, crown cover of more than 30% **in each hectare** | *forest land* (a) |
| Width | At least, or expected to reach, 30 m across on average | *forest land* (c) |

The two sources agree, including the "in each hectare" wording for crown cover.

The same page lists exclusions that go beyond the four headline conditions:
fruit and nut trees managed as food crops; shelter belts less than 30 m wide on
average **unless they join onto other forest land**; and small areas of trees
under 1 hectare **that are more than 15 m from adjacent forest**. As worded,
both exclusions depend on distance to other forest, so an area that fails the
width or area test on its own is not necessarily excluded.

The page also separates the forest-land definition from the pre-1990 /
post-1989 classification by establishment date, and notes LUC-class restrictions
on registering exotic forest on LUC class 1–6 land.

### Average-width guidance — checked 16 September 2026

[MPI dmsdocument 71887](https://www.mpi.govt.nz/dmsdocument/71887/direct) is
titled on the document itself **Registering areas of forest land less than 30
metres wide on average in the Emissions Trading Scheme**, published by Te Uru
Rākau – New Zealand Forest Service and dated **10 May 2026**. It is 2 pages long
and carries no separate version number; the date is its only version marker.
MPI's forest-land page links to it under the different label "How to calculate
the average width of an area, and how to register areas less than 30 metres wide
on average in the ETS".

- **Page 1** sets out the measurement: find the longest path from one end of the
  area to the other, draw a centre line along it, measure the width
  perpendicular to that centre line at 20 m increments, and average the
  measurements. A worked example reaches 31.69 m on a 1.1 ha area. The two width
  algorithms in this repository are screening diagnostics, not this method.
- **Page 2** describes two routes for areas narrower than 30 m on average: the
  whole area averages at least 30 m even though parts are narrower; or the
  narrow area lies next to, or within 15 m of, an eligible area of at least
  1 hectare that is in the same application (or an adjacent application by the
  same participant), or within 15 m of land the same participant has already
  registered as post-1989 forest land.

### Last checked 12 September 2026

- [How to map forestry for the ETS](https://www.mpi.govt.nz/forestry/forestry-in-the-emissions-trading-scheme/mapping-and-managing-forest-land-in-the-ets/how-to-map-forestry-for-the-emissions-trading-scheme)
  requires NZTM2000 or Chatham Islands Transverse Mercator 2000, closed
  polygons, no multipart polygons, and mapping that excludes ineligible land.
- [Geospatial Mapping Information Standard, 31 October 2025](https://www.mpi.govt.nz/dmsdocument/4756/direct)
  is the authoritative MPI standard for submitted mapping information.
- [Making sure mapped land is eligible](https://www.mpi.govt.nz/forestry/forestry-in-the-emissions-trading-scheme/mapping-and-managing-forest-land-in-the-ets/making-sure-mapped-land-is-eligible-for-the-emissions-trading-scheme)
  explains why historic imagery, applicant evidence, ownership or registered
  rights, species and land history remain assessor tasks.

## Open-data and basemap documentation

### LCDB v6.0 — checked 16 September 2026

[LCDB v6.0 – Land Cover Database version 6.0, Mainland, New Zealand](https://lris.scinfo.org.nz/layer/123148-lcdb-v60-land-cover-database-version-60-mainland-new-zealand/)
exists on the LRIS Portal as layer **123148**, published by Landcare Research
(Manaaki Whenua).

| Item | Value on LRIS |
|---|---|
| Date added / last updated | 2 October 2025 / 21 October 2025 |
| Licence | Creative Commons Attribution 4.0 International |
| DOI | [10.26060/WM99-RY32](https://doi.org/10.26060/WM99-RY32) |
| Stored CRS | NZGD2000 / NZTM2000, EPSG:2193 |
| Features | 542,789 polygons |
| Nominal time steps | summer 1996/97, 2001/02, 2007/08, 2012/13, 2018/19, 2023/24 |
| Class fields | `Class_2023`, `Class_2018`, `Class_2012`, `Class_2008`, `Class_2001`, `Class_1996` (integer) |
| Name fields | `Name_2023` … `Name_1996` (string) |
| Other fields | `Wetland_23`…`_96`, `Onshore_23`…`_96`, `EditAuthor`, `EditDate`, `LCDB_UID` |

v6.0 is the version now published and the one this project uses; the original
project plan named v5.0, which was not re-checked in this pass. The newest v6.0
fields are suffixed `_2023` (the 2023/24 time step), not `_2024`. This project
classifies units by `Name_2023` and keys them by `LCDB_UID`.

### Last checked 12 September 2026

- [LUCAS NZ Land Use Map 2020 v005](https://data.mfe.govt.nz/layer/117733-lucas-nz-land-use-map-2020-v005/)
  supplies nominal 1989, 2007, 2012, 2016 and 2020 land-use classes. This
  project uses 1989/2007 planted-forest polygons as mapped evidence only.
- [Territorial Authority 2026](https://datafinder.stats.govt.nz/layer/123497-territorial-authority-2026/)
  is the definitive Stats NZ district boundary source used to clip Gisborne.
- [DOC Public Conservation Land](https://services1.arcgis.com/3JjYDyG3oajxU6HO/arcgis/rest/services/DOC_Public_Conservation_Land/FeatureServer/0)
  is streamed from DOC's public ArcGIS organisation.
- [LINZ Basemaps technical documentation](https://basemaps.linz.govt.nz/docs/user-guide/technical-documentation/)
  documents aerial WMTS/XYZ access in NZTM2000 and Web Mercator and the required
  attribution.

## Interpretation decisions

R-04 and R-05 are project triage policies, not statutory eligibility rules.
Public conservation land is not automatically legally ineligible, and an LCDB
class cannot establish plantability, species, future height or future crown
cover. Their results therefore prioritise or remove cases from this specific
opportunity-screening queue; they do not decide ETS eligibility.

**R-01 and R-02 test each land-cover unit in isolation, but eligibility does
not.** Paragraph (c)(ii) of the forest-land definition keeps a narrow area that
is contiguous with qualifying forest land, and MPI's guidance lets an area under
30 m wide on average register when it lies within 15 m of an eligible area of at
least 1 hectare; its forest-land page excludes small tree areas under 1 hectare
only when they are more than 15 m from adjacent forest. Neither rule measures
adjacency, so a unit
quarantined for area or width may still be eligible through a neighbour.
Quarantine sends it to an assessor rather than rejecting it, which is the
correct direction for this gap, but the quarantine count should not be read as a
count of ineligible land.
