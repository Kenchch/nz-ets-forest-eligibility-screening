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

### 1. Width is materially method-dependent

The `2A/P` and `-15 m` erosion proxies disagree on **694 of 5,712 units
(12.15%)**. All 694 run in the same direction: a local 30 m core survives, but
the compactness-sensitive `2A/P` result is below 30 m.

![Real width disagreement cases](outputs/gisborne/figures/width_disagreement_cases.png)

The erosion test is retained as the primary narrow-strip diagnostic because it
directly tests whether a 30 m-wide core exists. It is **not** accepted as proof
of average width: every disagreement is quarantined under R-02. Long branching,
dumbbell and highly concave polygons can retain a core while still failing
MPI's formal centre-line average.

### 2. The real CRS failure mode is false rejection

In EPSG:2193, **4,223** polygons meet the 1 ha area threshold. If the same
geometries are transformed to EPSG:4326 and square degrees are naively compared
with 10,000 square metres, **all 4,223 are falsely rejected** and none are
falsely qualified. This corrects the initial project hypothesis rather than
forcing the result to match it. Every pipeline entry point therefore fails
loudly unless the CRS is EPSG:2193.

### 3. Preliminary imagery triage suggests substantial false positives

A fixed sample of **30** automated candidates was triaged against 2024
Gisborne imagery by an AI reviewer:

| Visual label | Count |
|---|---:|
| Plausible plantable | 13 |
| Already forested | 5 |
| Clearly not plantable | 12 |

The preliminary agreement rate is **13/30 (43.3%)**. Suggested false positives mainly
follow active riverbeds, coastal margins, roads or erosion features; five
others appear already forested or recently harvested. The [dated labels and
evidence notes](outputs/gisborne/review/review_labels.csv), [30 image
cards](outputs/gisborne/review/cards/) and higher-resolution dual-panel contact
sheets are committed. These labels are suggestions, not evidence that the
project author interpreted aerial imagery. A blank human-review template is
included and must be completed independently before any personal capability or
accuracy claim is made.

### 4. Screening disposition remains reviewable

| Result | Polygons |
|---|---:|
| Candidate review - clean | 2,520 |
| Candidate review - with advisory flag | 167 |
| **Candidate review total** | **2,687** |
| Quarantine | 2,801 |
| Excluded by project conservation policy | 224 |

The clean and advisory rows sum to the 2,687 candidate-review total. They are
shown separately so assessors can prioritise cases with minor mapped overlaps.
The automated reject/exclude rate is **52.96%**, below the consistent 80% batch
abort threshold. Failures remain in `quarantine.gpkg` with rule IDs, overlap
area and overlap percentage; no geometry is silently deleted.

### 5. Boundary mismatch can dominate whole-unit decisions

Under the earlier `>1 m²` rule, R-04 excluded 302 LCDB units. **78 had less
than 1% conservation overlap, yet those large source units represented
275,035.5 ha of the 283,698.7 ha flagged.** Their actual DOC intersection was
only 679.3 ha. R-03 had the same pattern: 209 of 900 flags were below 1%.

The project now treats an overlay as material only when it is both **greater
than 1 m² and at least 1% of the LCDB unit**; smaller positive intersections
remain explicit advisory flags. The 1% value is a documented sensitivity
threshold, not law. For assessment work, clipping authoritative parcel or
applicant stand geometry by verified overlap is preferable to rejecting an
entire land-cover mapping unit.

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
`intersects`. This exposes sliver overlaps caused by independently mapped,
differently generalised boundaries instead of turning them into whole-unit
decisions.

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

All vector processing is in NZTM2000 (EPSG:2193). The acquisition script queries
nationwide services by the Gisborne bounding box, repairs invalid source
geometries, clips to the district, explodes multipart mapping units, removes 36
numerical fragments below 1 m², and assigns stable `unit_id` values. The source
includes explicit non-plantable LCDB controls
so R-05 is tested rather than made tautological by preprocessing.

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
  fixed-seed 30-card imagery review
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

`LINZ_BASEMAP_API_KEY` is optional for the interactive review map. The main
pipeline propagates it when present and otherwise writes a valid key-free URL;
it never writes `YOUR_API_KEY`. Static committed review cards use the official
Gisborne imagery service and require no secret.

CI runs the test suite, verifies every pinned input, reproduces the real
Gisborne run and compares deterministic CSV findings plus semantic GeoPackage
content hashes. Volatile GeoPackage timestamps and PDF metadata are normalised.

## Tests and peer-review controls

- 20 tests cover CRS, area, both width methods, boundary-only contact, true
  overlap, each rule's own failure reason, API-key propagation and the 80%
  publication gate.
- The 0.99996 ha fixture displays as 1.0000 ha but correctly fails because the
  raw value controls R-01.
- Corrupted copies independently trigger small area, narrow geometry, wrong
  CRS, pre-1990 overlap and conservation overlap.
- `manual_review_rule_ids` always carries R-03/R-06/R-07/R-08 forward.

## ArcGIS Pro

[`arcgis/ets_screening.pyt`](arcgis/ets_screening.pyt) is a thin ArcGIS Pro
wrapper around the tested package and uses the same 80% threshold. It has been
statically reviewed but **not executed under `arcpy` on this machine** because
ArcGIS Pro is unavailable. The [reference PDF](arcgis/layout_map.pdf) is
generated by Matplotlib from the real Gisborne run; it is not represented as an
ArcGIS-authored layout.

## Limitations

- The LCDB streaming mirror simplifies geometry at 15 m, which can affect
  narrow-feature diagnostics. That tolerance is half the 30 m width threshold,
  so R-02 conclusions for narrow shapes are not reliable until the workflow is
  rerun from the original LRIS geometry.
- LCDB features are land-cover mapping units, **not cadastral parcels, ETS
  application areas, or forest stands**. After removing 36 sub-1 m² clipping
  fragments, unit areas still range from 0.0001 ha to 36,801.4 ha (median
  2.4853 ha). Production screening should intersect original LCDB coverage with
  LINZ NZ Primary Parcels or, preferably, applicant-supplied stand boundaries.
- R-02 remains a proxy. Formal MPI width uses perpendicular measurements at
  20 m intervals along a centre line following the longest path.
- LUCAS is mapped evidence, not a register of ETS status, liabilities or
  satisfied surrender obligations.
- LCDB class age and interpretation create false positives and negatives.
- R-04 and R-05 are prioritisation policies, not statutory eligibility tests.
- The committed imagery labels are preliminary AI suggestions. They do not
  demonstrate the author's imagery interpretation and require independent
  human completion of `review_labels_template.csv`.
- Species, future height/crown cover, title, forestry rights and evidence
  authenticity remain outside the automated scope.

## Repository map

```text
rules/       rule register and verified primary sources
data/        pinned real inputs, hashes, provenance and synthetic test fixtures
src/         validation, geometry diagnostics, rules, pipeline and review queue
tests/       corrupted-fixture and publication-gate tests
outputs/     real Gisborne findings, maps, GeoPackages and imagery review
notebooks/   executed real-data width/CRS/review walkthrough
arcgis/      thin ArcGIS Pro wrapper and reference PDF
```

Code is MIT licensed. Source data retain their publishers' licences and
attribution requirements. This independent portfolio project is not endorsed by
MPI, EPA, LINZ, MfE, DOC, Stats NZ, Gisborne District Council or Manaaki Whenua.
