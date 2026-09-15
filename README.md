# NZ ETS Forest Land — Spatial Eligibility Screening

> **This is a screening / triage tool, not an eligibility determination.**
> It identifies candidate areas for assessor review using the subset of ETS
> forest-land criteria that can be tested from open spatial data. Species,
> canopy cover and height at maturity, ownership and registered rights, and the
> complete 1989/1990 land-status history remain assessor decisions.

[![CI](https://github.com/Kenchch/nz-ets-forest-eligibility-screening/actions/workflows/ci.yml/badge.svg)](https://github.com/Kenchch/nz-ets-forest-eligibility-screening/actions/workflows/ci.yml)

An auditable Python/GeoPandas workflow for prioritising potential
**post-1989 forest-land** cases in **Gisborne District**. The committed primary
run uses 5,712 real LCDB v6 land-cover mapping units clipped against official open-data
layers; the small synthetic fixtures remain only for isolated tests.

![Gisborne screening overview](outputs/gisborne/figures/screening_overview.png)

## Findings

### 1. Boundary mismatch can dominate whole-unit decisions

Under the earlier `>1 m²` rule, R-04 excluded 302 LCDB units. **78 had less
than 1% conservation overlap, yet those large source units represented
275,035.5 ha of the 283,698.7 ha flagged.** Their actual DOC intersection was
only 679.3 ha. R-03 had the same pattern: 209 of 900 flags were below 1%.

Independently mapped, differently generalised boundaries produce sliver
intersections. Testing `intersects` promotes those slivers into whole-unit
rejections, so a few square metres of mapping disagreement can remove a
thousand-hectare unit from consideration.

The project now treats an overlay as material only when it is both **greater
than 1 m² and at least 1% of the LCDB unit**; smaller positive intersections
remain explicit advisory flags, listed per unit and worst-overlap-first in
[`advisory_candidates.csv`](outputs/gisborne/advisory_candidates.csv). The 1%
value is a documented sensitivity threshold, not law. For assessment work,
clipping authoritative parcel or applicant stand geometry by verified overlap is
preferable to rejecting an entire land-cover mapping unit.

### 2. Width is materially method-dependent

The `2A/P` and `-15 m` erosion proxies disagree on **694 of 5,712 units
(12.15%)**. All 694 run in the same direction: a local 30 m core survives, but
the compactness-sensitive `2A/P` result is below 30 m.

![Real width disagreement cases](outputs/gisborne/figures/width_disagreement_cases.png)

The erosion test is retained as the primary narrow-strip diagnostic because it
directly tests whether a 30 m-wide core exists. It is **not** accepted as proof
of average width: every disagreement is quarantined under R-02. Long branching,
dumbbell and highly concave polygons can retain a core while still failing
MPI's formal centre-line average.

That shape class is measurable rather than rhetorical. In **181 of the 694
(26.1%)** the surviving core is not one piece: the `-15 m` erosion splits it
into two or more separate parts, so the unit holds 30 m of width only in
disconnected lobes joined by necks narrower than 30 m. How many units qualify
depends on how small a fragment still counts as a lobe — requiring every part
to exceed 500 m² gives 53, and 1,000 m² gives 23. Like the 1% overlap rule,
that is a **documented sensitivity threshold, not a fixed property of the
data**; the headline 181 applies no threshold at all. The
[ArcGIS Pro layout](arcgis/layout_map.pdf) insets one of these units.

### 3. Imagery verification of the candidates is outstanding

R-05 can only show that a unit's *mapped* land-cover class is a plausible
planting proxy. Whether the ground is physically plantable at the imagery date
is an interpretation question, and it is the weakest link in everything above —
mapped classes age, and riverbeds, coastal margins, roads and erosion scars sit
inside units the automated rules pass.

The repository therefore ships this review as an open task rather than as a
result:

| Artefact | State |
|---|---|
| [Fixed-seed sample of 30 candidates](outputs/gisborne/review/review_sample_ids.csv) | Pinned; stable across reruns |
| [Dual-panel imagery cards](outputs/gisborne/review/cards/) | Rendered from 2024 Gisborne imagery |
| [Interactive review map](outputs/gisborne/review/review_map.html) | Offline; no CDN or API key required |
| [Blank label template](outputs/gisborne/review/review_labels_template.csv) | Awaiting an independent human reviewer |

**No visual agreement or false-positive rate is published here.**
`findings.csv` records `visual_review_status =
pending_independent_human_review` and nothing more. A rate appears only after a
named person completes `review_labels.csv` and
`scripts/ingest_review_labels.py` accepts it. That script refuses any label file
whose reviewer name looks automated: a model's reading of an aerial image is not
imagery-interpretation evidence and must not be reported as one.

## Rules and decision boundary

| Rule | Automated treatment | Decision limit |
|---|---|---|
| R-01 area at least 1 ha | Raw metric area controls the test; rounded value is display only | Other criteria remain |
| R-02 average width at least 30 m | Compare two proxies; erosion is primary; disagreement is quarantined | MPI centre-line measurement is still required |
| R-03 post-1989 rather than mapped pre-1990 | Material flag requires overlap >1 m² and >=1% of the LCDB unit; smaller overlaps are advisory | Absence of mapped overlap cannot prove land history |
| R-04 public conservation overlap | Project exclusion requires overlap >1 m² and >=1% of the LCDB unit; smaller overlaps are advisory | Project policy, not statutory ineligibility |
| R-05 potentially plantable current cover | Configurable LCDB proxy allow-list | Current cover cannot prove future forest |
| R-06 forest species | Not automated | Manual evidence required |
| R-07 crown cover over 30% in each hectare | Not automated | Manual evidence required |
| R-08 capable of 5 m at maturity | Not automated | Manual evidence required |

Boundary-only contact has zero area and does not fail R-03/R-04. The pipeline
records exact intersection area and source-unit proportion rather than using
`intersects`.

The [rule register](rules/rule_register.csv) and [source notes](rules/SOURCES.md)
link each interpretation to the current Act and MPI guidance.

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
unless the CRS is EPSG:2193.

The acquisition script queries nationwide services by the Gisborne bounding box,
repairs invalid source geometries, clips to the district, explodes multipart
mapping units, removes 36 numerical fragments below 1 m², and assigns stable
`unit_id` values. The source includes explicit non-plantable LCDB controls so
R-05 is tested rather than made tautological by preprocessing.

**Every disposition stays reviewable.** The run yields 2,687 candidates for
review (2,520 clean and 167 carrying an advisory flag), 2,801 quarantined and
224 excluded by project conservation policy — an automated reject/exclude rate
of 52.96%, below the 80% batch abort threshold. Failures keep their rule IDs,
overlap area and overlap percentage in `quarantine.gpkg`; no geometry is
silently deleted.

```text
official boundary + LCDB + LUCAS + DOC
                 |
       download, make-valid, clip
                 |
       assert EPSG:2193 + schema
                 |
 R-01 ... R-05 + overlap area/proportion
                 |
    candidate / quarantine / excluded
                 |
  fixed-seed 30-card imagery review queue
                 |
     independent human labels (outstanding)
```

## Reproduce

The committed processed inputs total about 12 MB and are pinned by SHA-256.
`reproduce.py` reads those files directly; it no longer rebuilds unused in-memory
demo shapes.

```bash
conda env create -f environment.yml
conda activate nz-ets-screening
pytest
python scripts/verify_checksums.py
python scripts/reproduce.py
```

To refresh from the public services:

```bash
python scripts/download_gisborne_data.py
python scripts/reproduce.py
python scripts/download_review_cards.py
```

To record the outstanding imagery review, copy the blank template, label all 30
cards, then ingest the result:

```bash
cp outputs/gisborne/review/review_labels_template.csv outputs/gisborne/review/review_labels.csv
python scripts/ingest_review_labels.py
python scripts/reproduce.py
```

The ingest step validates the label vocabulary, the reviewer, the date format,
the evidence notes and the unit IDs against the pinned sample before any number
reaches `findings.csv`.

`LINZ_BASEMAP_API_KEY` is optional for the interactive review map. The main
pipeline propagates it when present and otherwise writes a valid key-free URL;
it never writes `YOUR_API_KEY`. Leaflet is bundled into `review_map.html` rather
than loaded from a CDN, so the map opens on a restricted network, and the static
committed review cards use the official Gisborne imagery service and require no
secret.

CI runs the test suite, verifies every pinned input, reproduces the real
Gisborne run and compares deterministic CSV findings plus semantic GeoPackage
content hashes. GeoPackage output is byte-stable within an environment:
volatile timestamps and the SQLite writer-version stamp are normalised, so
rerunning the pipeline on unchanged inputs produces no diff to commit.

## Tests and peer-review controls

- 54 tests cover CRS, area, both width methods, boundary-only contact, true
  overlap, each rule's own failure reason, API-key propagation, GeoPackage byte
  stability, ArcGIS catalog-path translation, review-label validation and the
  80% publication gate.
- The 0.99996 ha fixture displays as 1.0000 ha but correctly fails because the
  raw value controls R-01.
- Corrupted copies independently trigger small area, narrow geometry, wrong
  CRS, pre-1990 overlap and conservation overlap.
- `manual_review_rule_ids` always carries R-03/R-06/R-07/R-08 forward.
- Machine-generated reviewer names are rejected by the imagery-review ingest, so
  automated labels cannot enter the committed evidence chain.

## ArcGIS Pro

[`arcgis/ets_screening.pyt`](arcgis/ets_screening.pyt) is a thin ArcGIS Pro
wrapper around the tested package and uses the same 80% threshold. It has been
**executed under ArcGIS Pro 3.7** against the committed Gisborne inputs: the run
screened all 5,712 units and reproduced the CLI results exactly, matching the
GeoPackages by semantic content hash and every deterministic table byte for
byte.

Running it flushed out two defects that static review had missed — an output
folder declared as `direction="Output"`, which made ArcGIS refuse any existing
folder, and ArcGIS catalog paths of the form `study.gpkg\main.layer`, which
GDAL cannot open, so the tool could not read a GeoPackage at all. Both are
fixed and covered by tests; see [`arcgis/README.md`](arcgis/README.md) for the
environment setup and the one expected difference in the review sample.

The [A3 layout](arcgis/layout_map.pdf) is an **ArcGIS Pro Layout export**,
authored through `arcpy.mp` by [`arcgis/build_layout.py`](arcgis/build_layout.py)
and rendered by Pro's own layout engine. It symbolises the committed
`candidates.gpkg` and `quarantine.gpkg` by `status` over the district boundary
and DOC public conservation land, and insets one R-02 width disagreement whose
30 m core survives in two lobes while its `2A/P` average width is 22.5 m. The
Matplotlib figures under `outputs/gisborne/figures/` remain the pipeline's own
reporting output and are unrelated to this layout.

## Limitations

- The LCDB streaming mirror simplifies geometry at 15 m, which can affect
  narrow-feature diagnostics. That tolerance is half the 30 m width threshold,
  so R-02 conclusions for narrow shapes are not reliable until the workflow is
  rerun from the original LRIS geometry. The multi-lobe count above inherits the
  same weakness: a 15 m erosion applied to geometry generalised at 15 m can
  sever a core at a neck the original mapping never had, so an unknown share of
  the smallest lobes are simplification artefacts rather than real shape.
- LCDB features are land-cover mapping units, **not cadastral parcels, ETS
  application areas, or forest stands**. After removing 36 sub-1 m² clipping
  fragments, unit areas still range from 0.0001 ha to 36,801.4 ha (median
  2.4853 ha). Production screening should intersect original LCDB coverage with
  LINZ NZ Primary Parcels or, preferably, applicant-supplied stand boundaries.
- Multipart mapping units are exploded, and each fragment is then screened
  independently under its own `-part-N` `unit_id`. One LCDB polygon can
  therefore appear as several separate dispositions; its parts are neither
  re-aggregated nor tested against R-01 or R-02 as a single area.
- R-02 remains a proxy. Formal MPI width uses perpendicular measurements at
  20 m intervals along a centre line following the longest path.
- LUCAS is mapped evidence, not a register of ETS status, liabilities or
  satisfied surrender obligations.
- LCDB class age and interpretation create false positives and negatives.
- R-04 and R-05 are prioritisation policies, not statutory eligibility tests.
- No imagery verification has been carried out. The automated candidate set has
  not been checked against what is visible on the ground, so the proportion of
  false positives within it is unmeasured.
- Species, future height/crown cover, title, forestry rights and evidence
  authenticity remain outside the automated scope.

## Repository map

```text
rules/       rule register and verified primary sources
data/        pinned real inputs, hashes, provenance and synthetic test fixtures
src/         validation, geometry diagnostics, rules, pipeline and review queue
tests/       corrupted-fixture and publication-gate tests
outputs/     real Gisborne findings, maps, GeoPackages and imagery review queue
notebooks/   executed real-data derivation of the width, CRS and overlay findings
arcgis/      thin ArcGIS Pro wrapper and reference PDF
```

Code is MIT licensed. Source data retain their publishers' licences and
attribution requirements. Leaflet 1.9.4 is bundled under its BSD-2-Clause
licence. This independent portfolio project is not endorsed by MPI, EPA, LINZ,
MfE, DOC, Stats NZ, Gisborne District Council or Manaaki Whenua.
