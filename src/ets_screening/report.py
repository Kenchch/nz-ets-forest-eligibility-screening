"""Static figures for review and portfolio presentation."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd
from matplotlib.figure import Figure
from matplotlib.image import imread
from matplotlib.lines import Line2D
from matplotlib.ticker import MaxNLocator
from shapely.affinity import translate

from .io_utils import build_datetime

# Figures are built on matplotlib.figure.Figure rather than pyplot, so
# importing this module never switches the caller's backend (for example a
# notebook's inline backend).

SCOPE_NOTE = "Screening / triage only - not an eligibility determination."


#: Matplotlib stamps its own version into every PNG as a `Software` tEXt chunk,
#: so a point release changes the committed figure bytes with no code or data
#: change. `None` suppresses the key entirely, which keeps the figures
#: comparable across environments the way the CSV and GeoPackage outputs
#: already are.
PNG_METADATA = {"Software": None}

STATUS_COLOURS = {
    "candidate_review": "#2b8c4b",
    "quarantine": "#e09f3e",
    "excluded": "#b83b5e",
}


def plot_screening_overview(
    results: gpd.GeoDataFrame,
    conservation: gpd.GeoDataFrame,
    pre1990: gpd.GeoDataFrame,
    destination: str | Path,
    title: str = "Spatial eligibility screening",
    data_note: str = "Provided inputs",
) -> None:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    minx, miny, _, _ = results.total_bounds
    x_origin = int(minx // 1000 * 1000)
    y_origin = int(miny // 1000 * 1000)

    def local(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        shifted = frame.copy()
        shifted.geometry = shifted.geometry.map(
            lambda geometry: translate(geometry, xoff=-x_origin, yoff=-y_origin)
        )
        return shifted

    display_results = local(results)
    display_conservation = local(conservation) if not conservation.empty else conservation
    display_pre1990 = local(pre1990) if not pre1990.empty else pre1990
    fig = Figure(figsize=(11.7, 8.3))
    ax = fig.subplots()
    for status, colour in STATUS_COLOURS.items():
        subset = display_results[display_results["status"] == status]
        if not subset.empty:
            subset.plot(
                ax=ax,
                facecolor=colour,
                edgecolor="#222222",
                linewidth=0.15 if len(results) > 200 else 0.8,
                alpha=0.78,
            )
    if not display_conservation.empty:
        display_conservation.boundary.plot(ax=ax, color="#6a3d9a", linewidth=2.0, linestyle="--")
    if not display_pre1990.empty:
        display_pre1990.boundary.plot(ax=ax, color="#1f78b4", linewidth=2.0, linestyle=":")
    # Labels help with tiny diagnostic fixtures but make a district-scale run
    # unreadable. Real feature IDs remain available in the GeoPackages.
    if len(display_results) <= 50:
        for _, row in display_results.iterrows():
            point = row.geometry.representative_point()
            ax.annotate(
                row["unit_id"],
                (point.x, point.y),
                ha="center",
                va="center",
                fontsize=8,
                weight="bold",
            )
    handles = [
        Line2D([0], [0], marker="s", color="none", markerfacecolor=colour, markeredgecolor="#222", markersize=10, label=status.replace("_", " ").title())
        for status, colour in STATUS_COLOURS.items()
    ]
    handles.extend(
        [
            Line2D([0], [0], color="#6a3d9a", lw=2, ls="--", label="Public conservation overlap"),
            Line2D([0], [0], color="#1f78b4", lw=2, ls=":", label="Mapped pre-1990 overlap"),
        ]
    )
    ax.legend(handles=handles, loc="upper right", frameon=True)
    ax.set_title(title, loc="left", fontsize=16, weight="bold", pad=30)
    ax.text(
        0.0,
        1.015,
        "Screening / triage only - not an eligibility determination. Polygons in EPSG:2193.",
        transform=ax.transAxes,
        fontsize=9,
        color="#444444",
    )
    ax.set_xlabel(f"NZTM2000 easting minus {x_origin:,} m")
    ax.set_ylabel(f"NZTM2000 northing minus {y_origin:,} m")
    ax.set_aspect("equal")
    ax.xaxis.set_major_locator(MaxNLocator(6))
    ax.yaxis.set_major_locator(MaxNLocator(5))
    ax.ticklabel_format(style="plain", useOffset=False)
    fig.text(0.01, 0.005, f"Data: {data_note}", fontsize=7, color="#555555")
    fig.tight_layout()
    fig.savefig(
        destination, dpi=180, bbox_inches="tight", metadata=PNG_METADATA
    )


def plot_width_comparison(
    comparison: pd.DataFrame,
    destination: str | Path,
    threshold_m: float = 30.0,
    data_note: str = "Provided inputs",
) -> None:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # unit_id breaks ties: many units share a width, and an unstable sort let
    # their order (and so the figure bytes) vary between library versions.
    ordered = comparison.sort_values(
        ["width_equivalent_rectangle_m", "unit_id"], kind="mergesort"
    ).reset_index(drop=True)
    colours = ordered["methods_disagree"].map({True: "#d95f02", False: "#2b8c4b"})
    fig = Figure(figsize=(10, 5.5))
    ax = fig.subplots()
    ax.scatter(
        ordered.index,
        ordered["width_equivalent_rectangle_m"],
        c=colours,
        s=16 if len(ordered) <= 100 else 5,
        alpha=0.75,
        linewidths=0,
    )
    threshold_label = f"{threshold_m:g} m threshold"
    ax.axhline(threshold_m, color="#333333", linestyle="--", linewidth=1.2, label=threshold_label)
    ax.set_ylabel("Equivalent-rectangle width (m, log scale)")
    ax.set_xlabel("Features ranked by equivalent-rectangle width")
    ax.set_title("Width-proxy comparison", loc="left", weight="bold")
    ax.set_yscale("log")
    handles = [
        Line2D([0], [0], color="#333333", lw=1.2, ls="--", label=threshold_label),
        Line2D([0], [0], marker="s", color="none", markerfacecolor="#d95f02", markersize=10, label="Erosion core and rectangle width disagree"),
        Line2D([0], [0], marker="s", color="none", markerfacecolor="#2b8c4b", markersize=10, label="Methods agree"),
    ]
    ax.legend(handles=handles)
    fig.text(0.01, 0.005, f"{SCOPE_NOTE} Data: {data_note}", fontsize=7, color="#555555")
    fig.tight_layout()
    fig.savefig(
        destination, dpi=180, bbox_inches="tight", metadata=PNG_METADATA
    )


def plot_layout_pdf(
    overview_png: str | Path,
    results: gpd.GeoDataFrame,
    comparison: pd.DataFrame,
    destination: str | Path,
    study_label: str = "User-supplied screening run",
    data_note: str = "Provided inputs",
    width_threshold_m: float = 30.0,
) -> None:
    """Build an A4 landscape reference sheet from the reproducible run."""

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    counts = results["status"].value_counts()
    disagreements = comparison[comparison["methods_disagree"]]
    example_values = disagreements["unit_id"].astype(str).head(3).tolist()
    example_lines = "\n".join(f"  {value}" for value in example_values) or "  none"

    fig = Figure(figsize=(11.69, 8.27), facecolor="white")
    fig.text(0.05, 0.955, "NZ ETS forest-land spatial screening", fontsize=20, weight="bold", color="#1a1a1a")
    fig.text(0.05, 0.925, study_label, fontsize=11, color="#555555")

    image_ax = fig.add_axes([0.045, 0.39, 0.91, 0.50])
    image_ax.imshow(imread(overview_png))
    image_ax.axis("off")

    summary_text = (
        "RUN SUMMARY\n"
        f"Input LCDB units: {len(results)}\n"
        f"Candidate review: {int(counts.get('candidate_review', 0))}\n"
        f"Quarantine: {int(counts.get('quarantine', 0))}\n"
        f"Excluded by project proxy: {int(counts.get('excluded', 0))}\n"
        f"Automated reject rate: {(results['status'] != 'candidate_review').mean():.1%}"
    )
    width_text = (
        "WIDTH DIAGNOSTIC\n"
        f"Proxy disagreements: {len(disagreements)}\n"
        "Examples:\n"
        f"{example_lines}\n"
        f"Rectangle width and -{width_threshold_m / 2:g} m erosion are triage only.\n"
        "Formal MPI width uses centre-line samples\n"
        "at 20 m intervals."
    )
    boundary_text = (
        "DECISION BOUNDARY\n"
        "Still unresolved: land history, species,\n"
        "mature height and cover, legal rights,\n"
        "and evidence authenticity. Failures retain\n"
        "rule IDs and geometry for review."
    )
    fig.text(0.06, 0.29, summary_text, fontsize=9.5, linespacing=1.45, va="top")
    fig.text(0.36, 0.29, width_text, fontsize=8.5, linespacing=1.35, va="top")
    fig.text(0.72, 0.29, boundary_text, fontsize=9.0, linespacing=1.4, va="top")
    fig.text(
        0.05,
        0.055,
        "SCREENING / TRIAGE ONLY - NOT AN ELIGIBILITY DETERMINATION | EPSG:2193",
        fontsize=9,
        weight="bold",
        color="#8c2f39",
    )
    fig.text(0.05, 0.03, f"Data: {data_note}", fontsize=6.5, color="#555555", wrap=True)
    fig.savefig(
        destination,
        format="pdf",
        metadata={
            "Title": f"NZ ETS forest-land spatial screening - {study_label}",
            "Creator": "nz-ets-forest-eligibility-screening",
            "CreationDate": build_datetime(),
            "ModDate": build_datetime(),
        },
    )
