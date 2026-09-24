# NZ ETS Forest Land — Spatial Eligibility Screening

> **This is a screening / triage tool, not an eligibility determination.**
> It identifies candidate areas for assessor review using the subset of ETS
> forest-land criteria that can be tested from open spatial data. Species,
> canopy cover and height at maturity, LUC-class registration limits, ownership
> and registered rights, and the complete 1989/1990 land-status history remain
> assessor decisions.

[![CI](https://github.com/Kenchch/nz-ets-forest-eligibility-screening/actions/workflows/ci.yml/badge.svg)](https://github.com/Kenchch/nz-ets-forest-eligibility-screening/actions/workflows/ci.yml)

An auditable Python/GeoPandas workflow for prioritising **potential
afforestation opportunities that could become post-1989 forest land** in
**Gisborne District**. The inputs are currently non-forest land cover, so the
output is a list of places worth an assessor's time, not of existing forest
that could be registered. The committed primary run uses 5,712 real LCDB v6
land-cover mapping units clipped against official open-data layers; the small
synthetic fixtures remain only for isolated tests.

![Gisborne screening overview](outputs/gisborne/figures/screening_overview.png)

## Findings

### 1. One relative threshold cannot judge overlap on units from 0.0001 to 36,801 ha

LCDB mapping units span eight orders of magnitude in area, and each overlay
decision is made for a whole unit. The project has used three materiality
rules, and the first two both failed on real data:

- **Any intersection over 1 m²** turned boundary slivers between independently
  generalised layers into whole-unit rejections: R-04 flagged 302 units and
  R-03 900.
- **At least 1% of the unit** fixed that, but 1% of a large unit is hundreds of
  hectares. On the earlier planted-forest-only evidence layer, **48 units
  carried at least 1 ha of mapped pre-1990 planted forest (1,012.4 ha in
  total, up to 146.9 ha in one unit), and 25 carried at least 1 ha of DOC land
  (668.6 ha, up to 297.2 ha), while being reported as minor "low-overlap"
  advisories.** These were real blocks of land, not slivers, and R-03 recorded
  them as passed.

The current rule does three things. Parts of an intersection **narrower than
15 m are removed first** by morphological opening, matching the mirror's 15 m
simplification; 20 conservation flags that the 1% rule treated as material
consisted only of such slivers (73 on the earlier pre-1990 layer, 348 on the
current one). What remains is **material at 1%
of the unit**. Remaining overlap of **1 ha or more below 1% is flagged
`clip-required`**, recorded as an advisory rather than a pass, and taken out of
the unit's `conflict_free_area_ha`. Excluding those units outright would be the
opposite error: the 25 DOC cases alone cover about 241,500 ha.

The 1% and 1 ha values are documented sensitivity thresholds, not law. Every flagged candidate is listed worst overlap first in
[`advisory_candidates.csv`](outputs/gisborne/advisory_candidates.csv). For
assessment work, clipping authoritative parcel or applicant stand geometry by
the verified overlap remains better than any whole-unit decision.

### 2. Natural forest in 1989 is the largest exclusion, and it was missing

Post-1989 status through para (a)(i) needs land that was *not forest land* on
31 December 1989, natural or planted. The first evidence layer held only LUCAS
planted forest (class 72). The 2026-09-24 refresh adds natural forest (class 71):
the evidence grew from 1,933 to 11,109 polygons, and natural forest present in
both 1989 and 2007 covers 232,944 ha of the district extent against 89,309 ha of
planted forest.

**Material R-03 overlaps rose from 603 to 2,388 units, and 1,684 units
(231,127 ha) are now quarantined for R-03 alone.** Candidates fell from 3,069
units (309,481 ha) to **1,641 units (115,060 ha, 114,105 ha outside every mapped
conflict)**, and the automated reject rate rose to 71.27% — below the 80% batch
gate, but close enough that a further conservative evidence layer could trip it.
Land that was forest in 1989 but not in 2007 is not excluded: para (a)(ii) can
still make it post-1989 forest land, so 256 units carry the advisory
`R-03-deforested-1990-2007` for manual review instead.

This moves the result in the conservative direction the project claims to take.
LUCAS remains mapped evidence, with its own minimum mapping unit and
generalisation, not a record of legal status.

### 3. Width is materially method-dependent

The earlier `2A/P` proxy and the `-15 m` erosion test disagreed on **694 of
5,712 units (12.15%)**, always in the same direction. That direction is not an
empirical finding: 2A/P is at most the inscribed diameter for any shape, and for
a W × L rectangle it is WL/(W+L), so a 33 m wide 1 ha strip reads 29.8 m. 293
of the 694 were convex (solidity ≥ 0.99), so most disagreements came from that
bias on compact shapes, not from branching outlines.

R-02 now needs **both** a surviving erosion core (eroding 1 mm less than half
the threshold, so a strip exactly 30 m wide passes) **and** an
**equivalent-rectangle width** of at least 30 m — the width of the rectangle
with the same area and perimeter, exact for any rectangle and low for ragged
outlines. 2A/P is still published for comparison.

![Real width disagreement cases](outputs/gisborne/figures/width_disagreement_cases.png)

**381 units keep a 30 m core but average below 30 m**, and are quarantined
under R-02 unless contiguous with qualifying land (below). In 126 of them the
core is split into separate fragments joined by narrower necks. How many
qualify as real "lobes" depends on how large a fragment must be: requiring at
least two fragments over 500 m² gives 33, and over 1,000 m² gives 14. Those
are sensitivity counts, not properties of the land; `build_findings.py`
computes all three. The [ArcGIS Pro layout](arcgis/layout_map_arcgispro.pdf)
insets one of these units.

### 4. Area and width are properties of forest areas, not of mapping units

A unit under 1 ha, or narrower than 30 m, can still belong to eligible forest
land through its neighbours: paragraph (c)(ii) keeps narrow areas contiguous
with qualifying land, and MPI excludes small areas only when they are more than
15 m from adjacent forest. Plantable units with no material conflict are now
chained into blocks wherever they lie within 15 m of each other. **133
candidates pass R-01 only through their block (`R-01-contiguous`) and 69 pass
R-02 only through a qualifying neighbour (`R-02-contiguous`).** Both stay
flagged, because mapped land cover stands in for forest and the shelter-belt
exclusion in (c)(i) cannot be separated from other narrow land.

### 5. Imagery verification of the candidates is outstanding

R-05 can only show that a unit's *mapped* land-cover class is a plausible
planting proxy. Whether the ground is physically plantable at the imagery date
is an interpretation question, and it is the weakest link in everything above.

| Artefact | State |
|---|---|
| [Stratified sample of 30 candidates](outputs/gisborne/review/review_sample_ids.csv) | Drawn 2026-09-24: 18 clean and 12 flagged candidates, pinned for reruns |
| [Dual-panel imagery cards](outputs/gisborne/review/cards/) | Rendered 2026-09-24 from 2024 Gisborne imagery; crosshair on the unit's interior point |
| [Review version](outputs/gisborne/review/review_version.json) | Records the sampler, sampling frame hash and card renderer |
| [Interactive review map](outputs/gisborne/review/review_map.html) | Offline controls and polygons; live LINZ imagery requires internet and a session API key |
| [Blank label template](outputs/gisborne/review/review_labels_template.csv) | Awaiting an independent human reviewer |

The sample and cards were replaced on 2026-09-24. The earlier sample had been
drawn by a since-removed sampler (`DataFrame.sample(n=30,
random_state=20260912)` over the 2,520 candidates without an advisory flag), so
flagged candidates — the ones most likely to change the answer — could not be
selected, and its cards drew the crosshair at the panel centre rather than on
the unit. The new sample is hash-ranked within two strata, clean and flagged,
in proportion to their size and with at least five flagged units; the cards
mark the unit's interior point and use an overview at least three zoom levels
wider than the detail panel.

`review_version.json` records the sampler, the sampling frame's size and
SHA-256, and the card renderer and commit. **Labels are refused unless both
the sample and the cards are current**, so labels made on an outdated set can
never reach `findings.json`. To draw a new sample, remove the old cards, run
`python scripts/reproduce.py --resample-review`, then render cards with
`python scripts/download_review_cards.py`.

One limit remains: **the imagery is coarser than its tile grid.** Level 10
tiles are 1.32 m per pixel, but the 2024 satellite mosaic appears to have a
native pixel nearer 10 m (the cards show it), too coarse for tracks or riverbed
edges in 1 ha units. LINZ sub-metre aerial imagery would be the better source.

**No visual agreement or false-positive rate is published here.**
`findings.json` records `visual_review_status =
pending_independent_human_review` and nothing more. A rate appears only after a
named person completes `review_labels.csv` and
`scripts/ingest_review_labels.py` accepts it.

## Rules and decision boundary

The [rule register](rules/rule_register.csv) is the single source of rule
names and testability; the package reads a byte-identical copy, and every row of
`rule_results.csv` carries an `outcome` (`pass`, `fail`, `advisory` or `manual`)
and the measured values behind it.

| Rule | Automated treatment | Decision limit |
|---|---|---|
| R-01 area at least 1 ha | Raw metric area; a smaller unit passes with advisory if its 15 m block reaches 1 ha; units under 1.05 ha are flagged near-threshold | Other criteria remain |
| R-02 average width at least 30 m | Erosion core **and** equivalent-rectangle width; a narrow unit passes with advisory next to a qualifying unit | MPI centre-line measurement is still required |
| R-03 post-1989 rather than mapped pre-1990 | LUCAS forest (natural or planted) in both 1989 and 2007: sliver-filtered overlap ≥1% is material, ≥1 ha below 1% is clip-required, smaller overlaps are advisory; forest in 1989 but not 2007 is an advisory for para (a)(ii) | Absence of mapped overlap cannot prove land history |
| R-04 public conservation overlap | As R-03; material overlap excludes the unit from this queue | Project policy, not statutory ineligibility |
| R-05 potentially plantable current cover | Configurable LCDB proxy allow-list | Current cover cannot prove future forest |
| R-06 forest species | Not automated | Manual evidence required |
| R-07 crown cover over 30% in each hectare | Not automated | Manual evidence required |
| R-08 capable of 5 m at maturity | Not automated | Manual evidence required |
| R-09 LUC class 1–6 registration limits | Not automated; no LUC layer supplied | Manual check required before exotic planting is treated as registrable |
| R-10 not area 1 / P90 land, not already registered | Not automated | Manual check of MPI records |
| R-11 registrable interest | Not automated | Title and rights evidence required |

Boundary-only contact has zero area and does not fail R-03/R-04. The pipeline
records exact intersection area, sliver-filtered area and source-unit
proportion rather than using `intersects`.

The [source notes](rules/SOURCES.md) link each interpretation to the current Act
and MPI guidance and quote the statutory definitions verbatim.

## Data and method

The reproducible study uses:

- Stats NZ Territorial Authority 2026 boundary;
- LCDB v6.0 land cover, streamed from an ArcGIS Living Atlas mirror and
  simplified by that service at 15 m;
- MfE LUCAS NZ Land Use Map 2020 v005;
- DOC Public Conservation Land;
- Gisborne District Council 2024 satellite imagery, credited by the service to
  LINZ, for the 30-card visual review.

All vector processing is in NZTM2000 (EPSG:2193). **The real CRS failure mode is
false rejection, not false qualification:** 4,223 polygons meet the 1 ha
threshold in EPSG:2193, and if those same geometries are transformed to
EPSG:4326 and square degrees are naively compared with 10,000 square metres, all
4,223 are falsely rejected and none are falsely qualified. That corrects the
initial project hypothesis, and every pipeline entry point now fails loudly
unless the CRS is NZTM2000 (a compound NZTM + vertical CRS is accepted).

The acquisition script queries nationwide services by the Gisborne bounding box,
repairs invalid source geometries, clips to the district, explodes multipart
mapping units and removes 36 numerical fragments below 1 m². It numbers the
parts of a multipart unit by their own geometry, largest first, so a refresh
cannot silently move a `-part-N` ID to different land. The 2026-09-24 refresh
applied that numbering for the first time: 326 part IDs now name a different
part of the same LCDB polygon than before, although the set of geometries is
unchanged. The source includes explicit
non-plantable LCDB controls so R-05 is tested rather than made tautological by
preprocessing.

**Every disposition stays reviewable.** The run yields 1,641 candidates for
review (965 clean and 676 carrying an advisory flag), 3,871 quarantined and
200 excluded by project conservation policy — an automated reject/exclude rate
of 71.27%, below the 80% batch abort threshold. Failures keep their rule IDs
and measurements in `quarantine.gpkg`; no geometry is silently deleted.

```text
official boundary + LCDB + LUCAS + DOC
                 |
       download, make-valid, clip
                 |
       assert EPSG:2193 + schema
                 |
 R-01 ... R-05 + sliver-filtered overlap + 15 m contiguity
                 |
    candidate / quarantine / excluded  (+ advisory flags)
                 |
     pinned 30-card imagery review queue
                 |
     independent human labels (outstanding)
```

## Reproduce

The committed processed inputs total about 13 MB and are pinned by SHA-256.
`reproduce.py` reads those files directly.

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
source .venv/bin/activate
python -m pip install -c constraints.txt ".[dev]"
python -m pytest
python scripts/verify_checksums.py
python scripts/reproduce.py
```

Use Python 3.11 or 3.12 for the tested reproduction environment. `constraints.txt`
pins all runtime, test and notebook dependencies, including transitive
dependencies, with Python/platform markers where versions differ. The package's
`pyproject.toml` retains compatibility ranges. CI installs the same constraints.
This is a pip version constraint set, not a hash-verified archive lock or a
Conda binary lock; `environment.yml` remains an optional, unpinned Conda setup
that CI does not exercise.

To deliberately update the pins, run
`uv pip compile pyproject.toml --extra dev --extra notebook --universal --python-version 3.11 --upgrade --output-file constraints.txt`,
then rerun the tests and reproduction checks on the CI matrix before accepting
the change. Build tooling and operating-system libraries are not pinned here.

To refresh from the public services:

```bash
python scripts/download_gisborne_data.py
python scripts/reproduce.py
python scripts/download_review_cards.py
```

A refresh is not expected to reproduce the committed input checksums: the
services are live and GeoPackage bytes vary with the GDAL version. Compare
`data/semantic_hashes.json` instead, which hashes content. The 2026-09-24
refresh recorded service versions, queries, retrieval times and raw-file hashes
in `gisborne_manifest.json`; the raw files themselves are not yet archived. See
[data/README.md](data/README.md#provenance-limits-of-the-committed-inputs).

To record the outstanding imagery review, copy the blank template, label all 30
cards, then ingest the result:

```bash
cp outputs/gisborne/review/review_labels_template.csv outputs/gisborne/review/review_labels.csv
python scripts/ingest_review_labels.py
python scripts/reproduce.py
```

The ingest step validates the label vocabulary, the reviewer, the date (ISO
format, between the queue's creation and today), the evidence notes and the
unit IDs against the pinned sample before any number reaches `findings.json`.
It never rewrites the reviewer's file; the summary records that file's SHA-256.

The interactive map asks for a LINZ API key only when you choose to load live
imagery. The key stays in that browser session and is sent to LINZ; it is never
read from `LINZ_BASEMAP_API_KEY` or embedded in generated files, and CI fails if
one appears in an output. The page carries a content security policy that lets
only its own scripts run and only LINZ tiles load, and it publishes only the
unit ID, class, area and status of each polygon.

`ets-screen` writes a `.ets_screening_output` marker into its output directory
and refuses a non-empty directory without one, so a mistyped `--output` cannot
overwrite unrelated files. Refreshes replace only generated files and restore
the previous files if publication fails. Exit codes distinguish a missing
input (2), invalid input (3), the reject-rate gate (4) and a refused output
directory (5).

`run_manifest.json` records the full rule configuration, the input file hashes
and source services, and the review sampling frame. Library versions and the
git commit go to `run_environment.json` beside it, which is not committed
because it varies by machine. File timestamps are fixed; set
`SOURCE_DATE_EPOCH` to stamp a release with its commit date instead.

CI runs ruff and the tests on Python 3.11/3.12 on Linux and Python 3.12 on
Windows using the built package, verifies every pinned input, reproduces the
real Gisborne run, and then fails on any change to a committed text output
(tables, JSON, manifest, review map), on any output file that appears or
disappears, on a published API key, and on a change in the semantic GeoPackage
hashes, which cover every layer, the CRS, field names and types and geometry
types at 1 mm / 6-decimal tolerance. It also executes the derivation notebook.
The PNG and PDF figures are **not** compared: their bytes depend on the
rendering stack, so they are regenerated rather than verified. A separate,
non-blocking job tests the latest dependency releases weekly.

## Tests and peer-review controls

- The suite covers CRS (including compound NZTM), area, all three width
  measures, boundary-only contact, sliver filtering, clip-required overlaps,
  contiguity, each rule's own failure reason, the audit-table outcomes,
  API-key non-disclosure and the map's content policy, GeoPackage byte
  stability, CLI exit codes, ArcGIS catalog-path translation, review-label
  validation, failed-write recovery, truncated and retried downloads, stable
  part numbering and imagery-card registration.
- Every rule threshold is pinned at its exact boundary — 1.0000 ha, a strip of
  exactly 30 m and one of 29.99 m, and overlaps of exactly 1 m² and exactly 1% —
  so the `>=` and `>` operators cannot be flipped without a test failing.
- The 0.999996 ha fixture displays as 1.0000 ha but correctly fails because the
  raw value controls R-01.
- Corrupted copies independently trigger small area, narrow geometry, wrong
  CRS, pre-1990 overlap and conservation overlap.
- The audit's own reproduction cases are regression tests: a random half of the
  real candidates is no longer rejected as overlapping, and a 33 m strip no
  longer fails R-02.
- `manual_review_rule_ids` carries every partially testable or untestable
  register rule (R-03, R-06 to R-11) forward.
- Recognisable machine-style reviewer names are rejected by the imagery-review
  ingest. This is a heuristic filter, not an authentication control: a machine
  can supply an ordinary person's name, and a few real names that contain model
  words are refused. Accountable sign-off, such as a signed commit or an
  approved pull request by the named reviewer, is the real control.
- Free-text reviewer and evidence fields beginning with a spreadsheet formula
  character are refused rather than quote-escaped, so the committed CSV cannot
  execute when opened and still round-trips byte for byte.

## ArcGIS Pro

[`arcgis/ets_screening.pyt`](arcgis/ets_screening.pyt) is a thin ArcGIS Pro
wrapper around the tested package and uses the same 80% threshold. It was
**re-executed under ArcGIS Pro 3.7 on 2026-09-24** against the current inputs
and rules, from a clone of `arcgispro-py3` with the geospatial dependencies
added, and reproduced the CLI tables byte for byte and the GeoPackages by
semantic hash. Expected failures are reported through `arcpy.AddError`. See
[`arcgis/README.md`](arcgis/README.md) for the environment setup and the one
expected difference in the review sample.

The [A3 layout](arcgis/layout_map_arcgispro.pdf) is an **ArcGIS Pro Layout
export**, authored through `arcpy.mp` by
[`arcgis/build_layout.py`](arcgis/build_layout.py) and rendered by Pro's own
layout engine; it was re-exported for the current results. Its counts and inset
text are read from the run outputs. It symbolises `candidates.gpkg` and
`quarantine.gpkg` by `status` over the district boundary and DOC public
conservation land, and insets `lcdb1000453434`, whose 30 m core survives in six
fragments while its equivalent-rectangle width is 22.8 m. It is unrelated to the
pipeline's own Matplotlib page, `outputs/gisborne/layout_map.pdf`.

## Limitations

- **Pre-1990 evidence is mapped land use, not legal status.** R-03 treats LUCAS
  forest in both 1989 and 2007 as material and forest cleared by 2007 as an
  advisory. LUCAS generalisation, its minimum mapping unit and the other
  statutory routes ((a)(iii)–(vii), exemptions, liabilities) are not assessed.
- **LUC class 1–6 registration limits are not screened.** MPI notes
  restrictions on registering exotic forest on LUC 1–6 land, and 94.6% of the
  candidate area is High Producing Exotic Grassland, the farm-to-forest case
  those limits target. The provisions have not been verified by this project
  and no LUC layer is used (R-09).
- **The raw downloads are not archived.** The manifest now records each
  service version, query and raw-file hash, but the upstream services are live,
  so the processed inputs cannot be re-derived later; archiving the raw files
  with a DOI (for example on Zenodo) is outstanding.
- The LCDB streaming mirror simplifies geometry at 15 m, which can affect
  narrow-feature diagnostics. That tolerance is half the 30 m width threshold,
  so R-02 conclusions for narrow shapes are not reliable until the workflow is
  rerun from the original LRIS geometry. The split-core counts inherit the same
  weakness: a 15 m erosion of geometry generalised at 15 m can sever a core at
  a neck the original mapping never had.
- LCDB features are land-cover mapping units, **not cadastral parcels, ETS
  application areas, or forest stands**. Unit areas range from 0.0001 ha to
  36,801.4 ha (median 2.4853 ha). Clip-required units in particular need
  authoritative parcel or applicant stand boundaries before any area figure is
  used. Production screening should intersect original LCDB coverage with LINZ
  NZ Primary Parcels or, preferably, applicant-supplied stand boundaries.
- The contiguity routes approximate forest adjacency from mapped land cover.
  They chain 15 m gaps transitively and cannot tell a shelter belt, which has
  no contiguity exception, from other narrow land.
- R-02 remains a proxy. Formal MPI width uses perpendicular measurements at
  20 m intervals along a centre line following the longest path.
- 92 plantable units lie within 5% of the 1 ha threshold; a mean boundary shift
  of about 1 m moves a unit that close across it. Passing ones carry
  `R-01-near-threshold`.
- LUCAS is mapped evidence, not a register of ETS status, liabilities or
  satisfied surrender obligations.
- LCDB class age and interpretation create false positives and negatives.
- R-04 and R-05 are prioritisation policies, not statutory eligibility tests.
- No imagery verification has been carried out; the sample and cards are ready
  for a named reviewer (Finding 5). The proportion of false positives in the
  candidate set is unmeasured.
- Existing but unregistered post-1989 forest, such as regenerating mānuka or
  kānuka, is outside the input classes and is not screened.
- Species, future height and crown cover, title, forestry rights, existing
  registration and evidence authenticity remain outside the automated scope.

## Repository map

```text
rules/       rule register and verified primary sources
data/        pinned real inputs, hashes, provenance and synthetic test fixtures
src/         validation, geometry diagnostics, rules, pipeline and review queue
tests/       corrupted-fixture, CLI and publication-gate tests
outputs/     real Gisborne findings, maps, GeoPackages and imagery review queue
notebooks/   executed real-data derivation of the width, CRS and overlay findings
arcgis/      thin ArcGIS Pro wrapper and ArcGIS Pro layout export
```

**Code:** MIT (see [LICENSE](LICENSE)). **Data and derived outputs:** third-party
data under CC BY 4.0 and other publisher terms, modified — see
[DATA_LICENSE.md](DATA_LICENSE.md) for rights holders, versions and required
attribution. Leaflet 1.9.4 is bundled under its BSD-2-Clause licence. Cite this
project with [CITATION.cff](CITATION.cff). This independent portfolio project is
not endorsed by MPI, EPA, LINZ, MfE, DOC, Stats NZ, Gisborne District Council
or Manaaki Whenua.
