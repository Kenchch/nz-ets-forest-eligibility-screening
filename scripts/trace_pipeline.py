"""Run every step in pipeline order and log how the data changes shape.

    uv run python scripts/trace_pipeline.py

The trace runs what scripts/reproduce.py runs, on the same pinned processed
inputs, but one module at a time and into outputs/trace/<run_id>/, so data/
and outputs/gisborne/ are only read. Each step logs what it takes in and hands
on: rows, columns, dtypes, nulls, ranges, a few rows, and what changed. At the
end every text output the trace wrote is compared with the committed one, and
its GeoPackages with semantic_hashes.json, so the log doubles as a
reproducibility check: the same comparisons CI makes. About two minutes.

    trace.log          full log: per step, input and output shape, columns,
                       dtypes, nulls, ranges, sample rows, what changed; the
                       steps' own log lines in between
    gisborne/          what reproduce.py would write to outputs/gisborne
    data_lineage.md    one table, one row per step
"""

from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import logging
import shutil
import subprocess
import sys
import textwrap
import time
from hashlib import sha256
from pathlib import Path

import geopandas as gpd
import pandas as pd

import build_findings
import ingest_review_labels
import reproduce
import semantic_hashes
from ets_screening import logs
from ets_screening.geometry import compare_width_methods
from ets_screening.load import assert_nztm2000, validate_candidates, validate_geometry
from ets_screening.review_labels import load_review_sample_ids
from ets_screening.rules import RuleConfig, _overlap_metrics, classify_pre1990_evidence, evaluate_rules
from ets_screening.screen import run_screening

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
COMMITTED = ROOT / "outputs" / "gisborne"
STEPS = 7  # inputs is step 0
# Every text output whose bytes CI holds to the committed copy (see
# .github/workflows/ci.yml) that the trace writes too.
EVIDENCE = (
    "summary.csv",
    "rule_results.csv",
    "width_method_comparison.csv",
    "advisory_candidates.csv",
    "run_manifest.json",
    ".ets_screening_output",
    "findings.csv",
    "findings.json",
    "review/review_sample_ids.csv",
    "review/review_labels_template.csv",
    "review/review_map.html",
    "review/review_summary.csv",
)
CODE_PATHS = ["src", "scripts", "pyproject.toml", "uv.lock"]

log = logging.getLogger("trace")
lineage: list[dict[str, str]] = []


# ---------------------------------------------------------------- formatting


def setup(out: Path) -> None:
    for stream in (sys.stdout, sys.stderr):  # a cp1252 pipe cannot print DOC's macrons
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    logs.console()  # the steps' own lines, as the pipeline shows them
    logs.capture_warnings()
    logs.log.setLevel(logging.INFO)
    out.mkdir(parents=True)
    log.setLevel(logging.INFO)
    log.propagate = False
    file = logging.FileHandler(out / "trace.log", encoding="utf-8")
    screen = logging.StreamHandler(sys.stdout)
    for h in (file, screen):
        h.setFormatter(logs.FORMAT)  # UTC, with the level, like the run log
        log.addHandler(h)
    # The steps' own lines go into trace.log too.
    logs.log.addHandler(file)
    logs.WARNINGS.addHandler(file)


def git_tag() -> str:
    """Short git sha, with -dirty when CODE_PATHS have uncommitted or untracked changes."""
    try:
        def git(*args: str) -> str:
            return subprocess.run(
                ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
            ).stdout.strip()

        sha = git("rev-parse", "--short", "HEAD")
        if git("status", "--porcelain", "--untracked-files=all", "--", *CODE_PATHS):
            sha += "-dirty"
        return sha
    except (OSError, subprocess.CalledProcessError):
        return "nogit"


def header(n: int, name: str, module: str, what: str) -> None:
    log.info("")
    log.info("=" * 78)
    log.info(f"[{n}/{STEPS}] {name}   ({module})   {what}")
    log.info("=" * 78)


def frame(label: str, df: pd.DataFrame, sample: int = 3, max_cols: int = 10) -> None:
    """Shape, memory, per-column dtype / nulls / range, and a few rows."""
    mem = df.memory_usage(deep=True).sum() / 2**20
    log.info(f"  {label}: {len(df):,} rows x {df.shape[1]} columns, {mem:,.1f} MB in memory")
    for c in df.columns:
        col = df[c]
        info = f"{str(col.dtype):<22} nulls {int(col.isna().sum()):>7,}"
        if isinstance(col, gpd.GeoSeries):
            kinds = col.geom_type.value_counts().to_dict()
            info += f"  EPSG:{col.crs.to_epsg() if col.crs else None}  {kinds}"
            if col.notna().any():
                area = col.area
                info += f"  area m2 [{area.min():,.4g}, {area.max():,.4g}]"
        elif pd.api.types.is_bool_dtype(col):
            info += f"  True {int(col.fillna(False).sum()):,}"
        elif pd.api.types.is_numeric_dtype(col):
            if col.notna().any():
                info += f"  range [{col.min():,.4g}, {col.max():,.4g}]"
        else:
            info += f"  {col.nunique():,} distinct values"
        log.info(f"      {str(c):<30} {info}")
    shown = [c for c in df.columns if not isinstance(df[c], gpd.GeoSeries)][:max_cols]
    if shown and len(df):
        log.info(f"      first {min(sample, len(df))} rows (geometry not shown):")
        log.info(textwrap.indent(df[shown].head(sample).to_string(max_colwidth=22), "      | "))


def table(df: pd.DataFrame) -> None:
    """A small frame in full: summaries and comparisons."""
    log.info(textwrap.indent(df.to_string(index=False, max_colwidth=60), "      | "))


def change(text: str) -> None:
    log.info(f"  -> what changed: {text}")


def record(step: str, module: str, inp: str, out: str, rows: str, what: str) -> None:
    lineage.append(
        {"step": step, "module": module, "input": inp, "output": out, "rows": rows, "change": what}
    )


def timed(fn, *args, **kwargs):
    t0 = time.perf_counter()
    result = fn(*args, **kwargs)
    log.info(f"  took {time.perf_counter() - t0:,.1f} s")
    return result


def quietly(fn, *args, **kwargs):
    """Call a script's main() without its printed result; the trace logs it instead."""
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args, **kwargs)


# ---------------------------------------------------------------- steps


def step_inputs() -> tuple[gpd.GeoDataFrame, ...]:
    header(0, "inputs", "data/processed", "the four pinned GeoPackages, checked against their hashes")
    bad = 0
    for raw in (DATA / "checksums.sha256").read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.startswith("#"):
            continue
        expected, relative = raw.split(maxsplit=1)
        ok = sha256((DATA / relative).read_bytes()).hexdigest() == expected
        bad += not ok
        log.info(f"  {relative}: {'matches its pin' if ok else 'DOES NOT MATCH ITS PIN'}")
    processed = DATA / "processed"
    layers = {
        name: gpd.read_file(processed / f"gisborne_{name}.gpkg")
        for name in ("boundary", "candidates", "pre1990_evidence", "conservation")
    }
    for name, layer in layers.items():
        frame(f"gisborne_{name}.gpkg", layer)
    change(
        "none. download_gisborne_data.py clipped these to the district, exploded multipart "
        "mapping units into single polygons and gave each LCDB part a stable unit_id; the "
        f"pipeline reads them as they are ({'all hashes match' if not bad else f'{bad} do not match'})"
    )
    candidates = layers["candidates"]
    record(
        "inputs", "data/processed", "public ArcGIS services",
        f"{len(candidates):,} units, {len(layers['pre1990_evidence']):,} pre-1990, "
        f"{len(layers['conservation']):,} conservation",
        f"{len(candidates):,} x {candidates.shape[1]}", "pinned by SHA-256; read unchanged",
    )
    return candidates, layers["pre1990_evidence"], layers["conservation"]


def step_validate(candidates, pre1990, conservation) -> None:
    header(1, "validate", "load.py", "fail-loud checks before any metric test")
    timed(validate_candidates, candidates)
    for name, layer in (("pre1990", pre1990), ("conservation", conservation)):
        assert_nztm2000(layer, name)
        if not layer.empty:
            validate_geometry(layer, name)
    log.info(
        f"  passed: EPSG:2193 everywhere, {len(candidates):,} unique unit_id values, every "
        "candidate a valid single-part Polygon, no overlap between candidates (each polygon "
        "intersected with the earlier ones it touches, within the 1e-06 m2 tolerance)"
    )
    change("none: validation only raises or passes")
    record("validate", "load.py", f"{len(candidates):,} units", "-", "-", "CRS, schema and geometry checked")


def step_widths(candidates) -> None:
    header(2, "width proxies", "geometry.py", "R-02's 30 m width measures, side by side")
    comparison = timed(compare_width_methods, candidates)
    frame("compare_width_methods()", comparison)
    disagree = comparison[comparison["methods_disagree"]]
    direction = disagree.groupby(["equivalent_rectangle_pass", "erosion_core_pass"]).size()
    log.info(f"  disagreements by (rectangle pass, erosion pass): {direction.to_dict()}")
    ap = int((comparison["area_perimeter_pass"] != comparison["erosion_core_pass"]).sum())
    log.info(f"  2A/P, a diagnostic only, disagrees with the erosion core on {ap:,} units")
    change(
        f"one row per unit, geometry dropped: {len(candidates):,} polygons -> {len(comparison):,} "
        "rows of three width measures; R-02 needs both the equivalent rectangle and the erosion "
        f"core, and {len(disagree):,} units pass only one of them"
    )
    record(
        "width proxies", "geometry.py", f"{len(candidates):,} polygons",
        f"{len(comparison):,} x {comparison.shape[1]}", "1 row per unit",
        f"rectangle and -15 m erosion (2A/P diagnostic); {len(disagree):,} disagreements",
    )


def step_overlaps(candidates, pre1990, conservation) -> None:
    header(3, "overlaps", "rules.py", "sliver-filtered intersection area and share of each unit, per overlay")
    config = RuleConfig()
    routes = classify_pre1990_evidence(pre1990)
    log.info(f"  pre-1990 evidence by statutory route: {routes.value_counts().to_dict()}")
    unit_area = candidates.geometry.area
    material_evidence = pre1990[routes == "forest_1989_and_2007"]
    for name, layer in (("pre1990", material_evidence), ("conservation", conservation)):
        raw, kept = timed(_overlap_metrics, candidates, layer, config.sliver_width_m)
        core = kept.area
        share = (core / unit_area * 100).fillna(0.0)
        above_area = raw > config.minimum_overlap_area_m2
        material = (core > config.minimum_overlap_area_m2) & (share >= config.minimum_overlap_pct)
        clip = ~material & (core >= config.clip_required_overlap_m2)
        log.info(
            f"  {name}: {int((raw > 0).sum()):,} units intersect it, {int(above_area.sum()):,} by "
            f"more than {config.minimum_overlap_area_m2:g} m2. With parts narrower than "
            f"{config.sliver_width_m:g} m removed, {int(material.sum()):,} reach "
            f"{config.minimum_overlap_pct:g}% of the unit (material), {int(clip.sum()):,} more keep "
            f"at least {config.clip_required_overlap_m2:,.0f} m2 (clip-required) and "
            f"{int((above_area & ~material & ~clip).sum()):,} are advisory"
        )
        log.info(
            f"      overlap m2 range [{raw.min():,.4g}, {raw.max():,.4g}], sliver-filtered share "
            f"of unit [{share.min():.4f}%, {share.max():.4f}%]"
        )
    deforested, _ = timed(
        _overlap_metrics, candidates, pre1990[routes == "forest_1989_deforested_by_2007"], 0.0
    )
    log.info(
        f"  pre1990 deforested by 2007: {int((deforested > config.minimum_overlap_area_m2).sum()):,} "
        f"units overlap it by more than {config.minimum_overlap_area_m2:g} m2 (advisory, para (a)(ii))"
    )
    change(
        "per unit and overlay: the raw overlap, what is left of it once slivers are removed, and "
        "that remainder's share of the unit; overlay polygons are unioned locally first, so "
        "overlapping source records are not counted twice"
    )
    record(
        "overlaps", "rules.py", f"{len(candidates):,} units x 2 overlays", "3 measures per unit and overlay",
        "1 row per unit",
        "sliver-filtered area and share; material at >1 m2 and >=1%, clip-required from 1 ha",
    )


def step_rules(candidates, pre1990, conservation):
    header(4, "rules", "rules.py", "R-01..R-05 per unit, a status, and the long audit table")
    results, audit = timed(evaluate_rules, candidates, pre1990, conservation)
    added = [c for c in results.columns if c not in candidates.columns]
    frame(f"evaluate_rules() wide results: {len(added)} columns added", results[["unit_id", *added]])
    frame("evaluate_rules() audit, one row per unit and rule", audit, sample=8)
    log.info(f"  status: {results['status'].value_counts().to_dict()}")
    flags = results["advisory_rule_ids"].fillna("").str.split("|").explode()
    log.info(f"  advisory flags: {flags[flags.ne('')].value_counts().sort_index().to_dict()}")
    manual = sorted(audit.loc[audit["outcome"] == "manual", "rule_id"].unique())
    change(
        f"{candidates.shape[1]} -> {results.shape[1]} columns (rule results, overlaps, widths, "
        f"advisory flags, status); the audit unpivots them to {len(audit):,} rows = "
        f"{len(results):,} units x {audit['rule_id'].nunique()} rules, {manual[0]}..{manual[-1]} "
        "marked manual"
    )
    record(
        "rules", "rules.py", f"{len(candidates):,} x {candidates.shape[1]}",
        f"results {len(results):,} x {results.shape[1]}, audit {len(audit):,} rows",
        f"x{len(audit) // len(results)} (audit)", "5 automated rules; candidate / quarantine / excluded",
    )


def step_screening(candidates, pre1990, conservation, out: Path) -> None:
    header(5, "screening", "screen.py", "what reproduce.py publishes: GeoPackages, tables, figures, review")
    sample = load_review_sample_ids(COMMITTED / "review" / "review_sample_ids.csv")
    manifest = timed(
        run_screening,
        candidates,
        pre1990,
        conservation,
        out,
        reject_rate_threshold=0.80,
        study_label=reproduce.STUDY_LABEL,
        data_note=reproduce.DATA_NOTE,
        review_sample_ids=sample,
        input_provenance=reproduce.input_provenance(DATA / "processed"),
    )
    for name in ("candidates.gpkg", "quarantine.gpkg", "review/review_queue.gpkg"):
        frame(name, gpd.read_file(out / name), sample=2)
    log.info("  summary.csv:")
    table(pd.read_csv(out / "summary.csv", dtype=str))
    frame("advisory_candidates.csv", pd.read_csv(out / "advisory_candidates.csv"), sample=3)
    for path in sorted(out.rglob("*")):
        if path.is_file() and path.suffix in {".png", ".pdf", ".html"}:
            log.info(f"  {path.relative_to(out).as_posix()}: {path.stat().st_size / 1024:,.0f} KB")
    log.info(f"  run_manifest.json: reject_rate {manifest['reject_rate']:.4f}")
    change(
        f"results split by status into two GeoPackages, the audit and width tables written as "
        f"CSV, and the pinned {len(sample)} review units copied out with a blank label template"
    )
    record(
        "screening", "screen.py + sample_review.py + report.py", "results + audit",
        "2 GeoPackages, 4 CSVs, manifest, figures, review bundle", "split by status",
        "staged, then each generated file replaced, rolled back on failure; 30-unit review queue",
    )


def step_findings(out: Path) -> None:
    header(6, "findings", "scripts/build_findings.py", "the evidence-backed findings, from the trace's outputs")
    saved = build_findings.OUTPUT
    build_findings.OUTPUT = out  # read the trace's tables, write beside them
    try:
        timed(quietly, build_findings.main)
    finally:
        build_findings.OUTPUT = saved
    findings = json.loads((out / "findings.json").read_text(encoding="utf-8"))
    for key, value in findings.items():
        log.info(f"      {key:<62} {value}")
    change(f"{len(findings)} named findings; tables and audit -> one key per claim the README makes")
    record(
        "findings", "scripts/build_findings.py", "screened GeoPackages + audit + widths",
        "findings.json, findings.csv, 1 figure", f"{len(findings)} findings", "aggregated",
    )


def step_review(out: Path) -> None:
    header(7, "review labels", "scripts/ingest_review_labels.py", "the human imagery review, or its pending state")
    review = out / "review"
    labels = COMMITTED / "review" / "review_labels.csv"
    if labels.exists():  # a completed review lives beside the committed queue
        # Labels are accepted only with the record of the sample and cards they were made on.
        for name in (labels.name, "review_version.json"):
            shutil.copy2(COMMITTED / "review" / name, review / name)
    status = timed(quietly, ingest_review_labels.main, ["--review-dir", str(review)])
    log.info(f"  ingest_review_labels: exit status {status}")
    table(pd.read_csv(review / "review_summary.csv", dtype=str))
    change("labels validated against the pinned sample; summary written (pending or complete)")
    record(
        "review labels", "scripts/ingest_review_labels.py", "review_sample_ids.csv (+ labels)",
        "review_summary.csv", "1 row per metric", "pending until a named person labels the 30 cards",
    )


# ---------------------------------------------------------------- checks


def compare_with_committed(out: Path) -> None:
    log.info("")
    log.info("=" * 78)
    log.info("Reproducibility check: the trace's outputs vs the committed ones")
    log.info("=" * 78)
    for relative in EVIDENCE:
        new, old = out / relative, COMMITTED / relative
        if not old.exists():
            log.info(f"  {relative}: nothing committed to compare with")
            continue
        # Text comparison, so a CRLF checkout on Windows compares like Linux CI.
        if new.read_text(encoding="utf-8") == old.read_text(encoding="utf-8"):
            log.info(f"  {relative}: identical")
        else:
            log.warning(f"  {relative}: DIFFERS from outputs/gisborne/{relative}")
    expected = json.loads(semantic_hashes.MANIFEST.read_text(encoding="utf-8"))
    for relative, digest in expected.items():
        if semantic_hashes.semantic_hash(out / relative) == digest:
            log.info(f"  {relative}: same content as semantic_hashes.json")
        else:
            log.warning(f"  {relative}: content DIFFERS from semantic_hashes.json")


def write_lineage(out: Path) -> None:
    lines = [
        "# Data lineage (trace run)",
        "",
        "| Step | Module | Input | Output | Rows | What happened to the structure |",
        "|---|---|---|---|---|---|",
    ]
    lines += [
        f"| {r['step']} | `{r['module']}` | {r['input']} | {r['output']} | {r['rows']} | {r['change']} |"
        for r in lineage
    ]
    (out / "data_lineage.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + git_tag()
    out = ROOT / "outputs" / "trace" / run_id
    setup(out)
    log.info(f"trace run {run_id}; everything is written under {logs.rel(out)}")
    t0 = time.perf_counter()
    candidates, pre1990, conservation = step_inputs()
    step_validate(candidates, pre1990, conservation)
    step_widths(candidates)
    step_overlaps(candidates, pre1990, conservation)
    step_rules(candidates, pre1990, conservation)
    step_screening(candidates, pre1990, conservation, out / "gisborne")
    step_findings(out / "gisborne")
    step_review(out / "gisborne")
    write_lineage(out)
    compare_with_committed(out / "gisborne")
    log.info("")
    log.info(f"done in {time.perf_counter() - t0:,.0f} s; log {logs.rel(out / 'trace.log')}")


if __name__ == "__main__":
    main()
