"""Author and export the A3 screening layout in ArcGIS Pro.

Run with the ArcGIS Pro conda python so ``arcpy`` is importable, for example::

    "%PROGRAMFILES%\\ArcGIS\\Pro\\bin\\Python\\Scripts\\propy.bat" arcgis\\build_layout.py

Every element is created through ``arcpy.mp`` and the PDF is written by
``Layout.exportToPDF``, so the output is rendered by ArcGIS Pro's own layout
engine rather than by the Matplotlib reporting code in ``src/``.

The project file it builds is a normal ``.aprx``: open it in ArcGIS Pro to
adjust the cartography by hand and re-export.

Only ``arcpy`` is required. ArcGIS reads the committed GeoPackages directly, so
the screening dependencies (geopandas and friends) do not need to be installed
into the ArcGIS environment to produce the map.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import tempfile

import arcpy
import arcpy.mp as mp


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLANK_TEMPLATE = os.path.join(
    arcpy.GetInstallInfo()["InstallDir"],
    r"Resources\ArcToolBox\Services\routingservices\data\Blank.aprx",
)

CANDIDATES = os.path.join(ROOT, r"outputs\gisborne\candidates.gpkg\main.candidates")
QUARANTINE = os.path.join(ROOT, r"outputs\gisborne\quarantine.gpkg\main.quarantine")
BOUNDARY = os.path.join(ROOT, r"data\processed\gisborne_boundary.gpkg\main.gisborne_boundary")
CONSERVATION = os.path.join(
    ROOT, r"data\processed\gisborne_conservation.gpkg\main.gisborne_conservation"
)

SUMMARY = os.path.join(ROOT, r"outputs\gisborne\summary.csv")
FINDINGS = os.path.join(ROOT, r"outputs\gisborne\findings.json")


def _read_results():
    """Read the counts shown on the map from the committed run outputs.

    Hard-coding them let the layout keep stale numbers after a rule change.
    """

    with open(SUMMARY, encoding="utf-8", newline="") as handle:
        summary = {row["metric"]: row["value"] for row in csv.DictReader(handle)}
    with open(FINDINGS, encoding="utf-8") as handle:
        findings = json.load(handle)
    return summary, findings


SUMMARY_VALUES, FINDINGS_VALUES = _read_results()
INSET = FINDINGS_VALUES["layout_inset"]
#: A branching unit whose 30 m erosion core survives in separate fragments while
#: its average-width proxy fails. See README finding 2.
INSET_UNIT = INSET["unit_id"]

STATUS_COLOURS = {
    "candidate_review": [64, 145, 74, 100],
    "quarantine": [235, 158, 47, 100],
    "excluded": [176, 60, 60, 100],
}
STATUS_LABELS = {
    "candidate_review": f"Candidate for assessor review ({int(SUMMARY_VALUES['candidate_review']):,})",
    "quarantine": f"Quarantined - rule failure ({int(SUMMARY_VALUES['quarantine']):,})",
    "excluded": f"Excluded - project conservation policy ({int(SUMMARY_VALUES['excluded']):,})",
}

TITLE = "NZ ETS Post-1989 Forest-Land Screening - Gisborne District"
SUBTITLE = (
    f"Automated spatial triage of {int(SUMMARY_VALUES['total_features']):,} LCDB v6 "
    "land-cover mapping units against the subset of forest-land criteria testable "
    "from open data"
)
DISCLAIMER = "SCREENING / TRIAGE ONLY - NOT AN ELIGIBILITY DETERMINATION"
SOURCES = (
    "Sources (all CC BY 4.0, modified): LCDB v6.0 (Manaaki Whenua - Landcare Research); "
    "LUCAS NZ Land Use Map 2020 v005 (MfE); Public Conservation Land (DOC, Crown); "
    "Territorial Authority 2026 (Stats NZ). "
    "Independent portfolio project; not endorsed by MPI, EPA, LINZ, MfE, DOC or Stats NZ."
)
CRS_NOTE = (
    "Coordinate system: NZGD2000 / New Zealand Transverse Mercator 2000 (NZTM2000), "
    "EPSG:2193. All area and width tests computed in metres."
)
INSET_NOTE = (
    f"{INSET_UNIT}: a 30 m erosion core survives in {INSET['erosion_core_parts']} separate "
    f"fragments ({INSET['erosion_core_parts_over_500_m2']} larger than 500 m2), yet its "
    f"equivalent-rectangle width is {INSET['equivalent_rectangle_m']:.1f} m. One of "
    f"{int(SUMMARY_VALUES['width_method_disagreements']):,} units where the two R-02 proxies "
    "disagree; all are quarantined for assessor review, not rejected."
)


def point(x, y):
    return arcpy.Point(x, y)


def envelope(x, y, width, height):
    """A page-units rectangle as a polygon, for element placement."""

    corners = arcpy.Array(
        [point(x, y), point(x, y + height), point(x + width, y + height), point(x + width, y)]
    )
    return arcpy.Polygon(corners)


def feature_extent(feature_class, where=None, margin=0.0):
    """Union extent of matching features, in the data's own CRS (EPSG:2193)."""

    bounds = None
    with arcpy.da.SearchCursor(feature_class, ["SHAPE@"], where) as cursor:
        for (shape,) in cursor:
            if shape is None:
                continue
            extent = shape.extent
            values = [extent.XMin, extent.YMin, extent.XMax, extent.YMax]
            if bounds is None:
                bounds = values
            else:
                bounds = [
                    min(bounds[0], values[0]), min(bounds[1], values[1]),
                    max(bounds[2], values[2]), max(bounds[3], values[3]),
                ]
    if bounds is None:
        raise SystemExit(f"no features matched in {feature_class} ({where})")
    return arcpy.Extent(
        bounds[0] - margin, bounds[1] - margin, bounds[2] + margin, bounds[3] + margin
    )


def add(map_object, path, name):
    layer = map_object.addDataFromPath(path)
    layer.name = name
    return layer


def unique_values(layer, field, outline=(80, 80, 80, 100), width=0.2):
    """Apply a unique-value renderer and colour each status class explicitly."""

    symbology = layer.symbology
    symbology.updateRenderer("UniqueValueRenderer")
    symbology.renderer.fields = [field]
    layer.symbology = symbology

    symbology = layer.symbology
    for group in symbology.renderer.groups:
        for item in group.items:
            value = item.values[0][0]
            if value in STATUS_COLOURS:
                item.symbol.color = {"RGB": STATUS_COLOURS[value]}
                item.symbol.outlineColor = {"RGB": list(outline)}
                item.symbol.outlineWidth = width
                item.label = STATUS_LABELS.get(value, value)
    layer.symbology = symbology
    return layer


def solid(layer, fill, outline, outline_width=1.0):
    symbology = layer.symbology
    symbology.updateRenderer("SimpleRenderer")
    symbology.renderer.symbol.color = {"RGB": fill}
    symbology.renderer.symbol.outlineColor = {"RGB": outline}
    symbology.renderer.symbol.outlineWidth = outline_width
    layer.symbology = symbology
    return layer


def build(aprx_path: str, pdf_path: str, png_path: str | None) -> None:
    arcpy.env.overwriteOutput = True
    if os.path.exists(aprx_path):
        os.remove(aprx_path)
    shutil.copy2(BLANK_TEMPLATE, aprx_path)
    aprx = mp.ArcGISProject(aprx_path)

    main_map = aprx.listMaps()[0]
    main_map.name = "Gisborne screening"
    for layer in list(main_map.listLayers()):
        main_map.removeLayer(layer)          # drop the template basemap
    main_map.spatialReference = arcpy.SpatialReference(2193)

    # Added bottom-up: the last layer added draws on top.
    solid(add(main_map, CONSERVATION, "Public conservation land (DOC)"),
          [150, 186, 158, 60], [92, 133, 102, 85], 0.4)
    unique_values(add(main_map, QUARANTINE, "Quarantined and excluded"), "status")
    unique_values(add(main_map, CANDIDATES, "Candidates for review"), "status")
    solid(add(main_map, BOUNDARY, "Gisborne District boundary"),
          [0, 0, 0, 0], [35, 35, 35, 100], 1.4)

    inset_map = aprx.createMap("Width disagreement inset", "Map")
    for layer in list(inset_map.listLayers()):
        inset_map.removeLayer(layer)
    inset_map.spatialReference = arcpy.SpatialReference(2193)
    unique_values(add(inset_map, QUARANTINE, "Quarantined and excluded"), "status")
    unique_values(add(inset_map, CANDIDATES, "Candidates for review"), "status")
    highlight = add(inset_map, QUARANTINE, f"R-02 disagreement {INSET_UNIT}")
    highlight.definitionQuery = f"unit_id = '{INSET_UNIT}'"
    solid(highlight, [255, 255, 255, 0], [219, 24, 82, 100], 2.2)

    layout = aprx.createLayout(420, 297, "MILLIMETER", "Gisborne screening A3")

    main_frame = layout.createMapFrame(envelope(12, 42, 196, 228), main_map, "Main map frame")
    main_frame.camera.setExtent(feature_extent(BOUNDARY, margin=3000.0))

    inset_frame = layout.createMapFrame(
        envelope(216, 158, 192, 112), inset_map, "Inset map frame"
    )
    inset_frame.camera.setExtent(
        feature_extent(QUARANTINE, f"unit_id = '{INSET_UNIT}'", margin=120.0)
    )

    aprx.createTextElement(
        layout, point(12, 285), "POINT", TITLE, 18, "Tahoma", "Bold", name="Title"
    )
    aprx.createTextElement(
        layout, envelope(12, 272, 196, 9), "POLYGON", SUBTITLE, 8,
        "Tahoma", "Regular", name="Subtitle",
    )
    aprx.createTextElement(
        layout, point(216, 277), "POINT", "Inset: R-02 width-method disagreement",
        9, "Tahoma", "Bold", name="InsetTitle",
    )
    aprx.createTextElement(
        layout, envelope(216, 140, 192, 14), "POLYGON", INSET_NOTE, 7.5,
        "Tahoma", "Regular", name="InsetNote",
    )
    aprx.createTextElement(
        layout, point(12, 34), "POINT", DISCLAIMER, 11, "Tahoma", "Bold", name="Disclaimer"
    )
    aprx.createTextElement(
        layout, envelope(12, 18, 285, 12), "POLYGON", SOURCES, 7,
        "Tahoma", "Regular", name="Sources",
    )
    aprx.createTextElement(
        layout, envelope(12, 8, 285, 8), "POLYGON", CRS_NOTE, 7,
        "Tahoma", "Regular", name="CrsNote",
    )

    legend = layout.createMapSurroundElement(
        envelope(216, 84, 192, 50), "LEGEND", main_frame, None, "Legend"
    )
    legend.elementWidth, legend.elementHeight = 192, 50
    legend.title = "Screening disposition"
    legend.showTitle = True
    # Layer names and field headings are CIM-only properties at Pro 3.7.
    definition = legend.getDefinition("V3")
    for item in definition.items:
        item.showLayerName = False
        item.showHeading = False
        item.showGroupLayerName = False
        for attribute in ("labelSymbol", "descriptionSymbol"):
            symbol = getattr(item, attribute, None)
            if symbol is not None and getattr(symbol, "symbol", None) is not None:
                symbol.symbol.height = 8
    legend.setDefinition(definition)

    def style(item_type, wildcard):
        items = aprx.listStyleItems("ArcGIS 2D", item_type, wildcard)
        if not items:
            raise SystemExit(f"style item not found: {item_type} {wildcard}")
        return items[0]

    scale_bar = layout.createMapSurroundElement(
        point(216, 74), "SCALE_BAR", main_frame,
        style("SCALE_BAR", "Alternating Scale Bar 1 Metric"), "Scale bar",
    )
    scale_bar.elementWidth = 70
    layout.createMapSurroundElement(
        point(392, 70), "NORTH_ARROW", main_frame,
        style("NORTH_ARROW", "ArcGIS North 1"), "North arrow",
    )

    aprx.save()
    print(f"project: {aprx_path}")
    print(f"main map scale 1:{int(main_frame.camera.scale):,}")
    if png_path:
        layout.exportToPNG(png_path, resolution=110)
        print(f"preview: {png_path}")
    layout.exportToPDF(pdf_path, resolution=300, image_quality="BEST")
    print(f"pdf: {pdf_path} ({os.path.getsize(pdf_path):,} bytes)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", default=os.path.join(ROOT, r"arcgis\layout_map_arcgispro.pdf"))
    parser.add_argument(
        "--aprx",
        default=os.path.join(tempfile.gettempdir(), "ets_screening_layout.aprx"),
        help="Where to write the ArcGIS Pro project; open it to refine the map by hand.",
    )
    parser.add_argument("--png", default=None, help="Optional preview image.")
    args = parser.parse_args()
    build(args.aprx, args.pdf, args.png)


if __name__ == "__main__":
    main()
