"""Static figures for review and portfolio presentation."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.ticker import MaxNLocator
from shapely.affinity import translate


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
    title: str = "Gisborne study design - synthetic demonstration",
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
    fig, ax = plt.subplots(figsize=(11.7, 8.3))
    for status, colour in STATUS_COLOURS.items():
        subset = display_results[display_results["status"] == status]
        if not subset.empty:
            subset.plot(ax=ax, facecolor=colour, edgecolor="#222222", linewidth=0.8, alpha=0.78)
    if not display_conservation.empty:
        display_conservation.boundary.plot(ax=ax, color="#6a3d9a", linewidth=2.0, linestyle="--")
    if not display_pre1990.empty:
        display_pre1990.boundary.plot(ax=ax, color="#1f78b4", linewidth=2.0, linestyle=":")
    for _, row in display_results.iterrows():
        point = row.geometry.representative_point()
        ax.annotate(row["parcel_id"], (point.x, point.y), ha="center", va="center", fontsize=8, weight="bold")
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
        "Screening / triage only - not an eligibility determination. Synthetic parcels in EPSG:2193.",
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
    fig.tight_layout()
    fig.savefig(destination, dpi=180, bbox_inches="tight")
    plt.close(fig)


def plot_width_comparison(comparison: pd.DataFrame, destination: str | Path) -> None:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    ordered = comparison.sort_values("width_area_perimeter_m")
    colours = ordered["methods_disagree"].map({True: "#d95f02", False: "#2b8c4b"})
    fig, ax = plt.subplots(figsize=(10, 5.5))
    ax.bar(ordered["parcel_id"], ordered["width_area_perimeter_m"], color=colours)
    ax.axhline(30.0, color="#333333", linestyle="--", linewidth=1.2, label="30 m threshold")
    ax.set_ylabel("2A/P width proxy (m)")
    ax.set_xlabel("Synthetic parcel")
    ax.set_title("Two width proxies disagree on irregular shapes", loc="left", weight="bold")
    handles = [
        Line2D([0], [0], color="#333333", lw=1.2, ls="--", label="30 m threshold"),
        Line2D([0], [0], marker="s", color="none", markerfacecolor="#d95f02", markersize=10, label="Methods disagree"),
        Line2D([0], [0], marker="s", color="none", markerfacecolor="#2b8c4b", markersize=10, label="Methods agree"),
    ]
    ax.legend(handles=handles)
    fig.tight_layout()
    fig.savefig(destination, dpi=180, bbox_inches="tight")
    plt.close(fig)


def plot_layout_pdf(
    overview_png: str | Path,
    results: gpd.GeoDataFrame,
    comparison: pd.DataFrame,
    destination: str | Path,
) -> None:
    """Build an A4 landscape reference sheet from the reproducible run."""

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    counts = results["status"].value_counts()
    disagreements = comparison[comparison["methods_disagree"]]
    disagreement_ids = ", ".join(disagreements["parcel_id"].astype(str)) or "none"

    fig = plt.figure(figsize=(11.69, 8.27), facecolor="white")
    fig.text(0.05, 0.955, "NZ ETS forest-land spatial screening", fontsize=20, weight="bold", color="#1a1a1a")
    fig.text(0.05, 0.925, "Gisborne study design - synthetic demonstration", fontsize=11, color="#555555")

    image_ax = fig.add_axes([0.045, 0.39, 0.91, 0.50])
    image_ax.imshow(plt.imread(overview_png))
    image_ax.axis("off")

    summary_text = (
        "RUN SUMMARY\n"
        f"Input features: {len(results)}\n"
        f"Candidate review: {int(counts.get('candidate_review', 0))}\n"
        f"Quarantine: {int(counts.get('quarantine', 0))}\n"
        f"Excluded by project proxy: {int(counts.get('excluded', 0))}\n"
        f"Automated reject rate: {(results['status'] != 'candidate_review').mean():.1%}"
    )
    width_text = (
        "WIDTH DIAGNOSTIC\n"
        f"Proxy disagreements: {len(disagreements)} ({disagreement_ids})\n"
        "2A/P and -15 m erosion are triage only.\n"
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
    fig.text(0.37, 0.29, width_text, fontsize=9.5, linespacing=1.45, va="top")
    fig.text(0.69, 0.29, boundary_text, fontsize=9.5, linespacing=1.45, va="top")
    fig.text(
        0.05,
        0.045,
        "SCREENING / TRIAGE ONLY - NOT AN ELIGIBILITY DETERMINATION | EPSG:2193 | Synthetic geometries",
        fontsize=9,
        weight="bold",
        color="#8c2f39",
    )
    fig.savefig(
        destination,
        format="pdf",
        metadata={"Title": "NZ ETS forest-land spatial screening - synthetic demonstration", "Author": "Feng Jiang"},
    )
    plt.close(fig)
