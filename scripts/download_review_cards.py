"""Render the 30 pinned review cards for the Gisborne queue from GDC imagery tiles."""

from __future__ import annotations

from datetime import datetime, timezone
import io
import argparse
import json
import math
import urllib.parse
import urllib.request
from pathlib import Path

import geopandas as gpd
from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import Point

from ets_screening.review_labels import validate_review_sample_ids

ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / "outputs" / "gisborne" / "review" / "review_queue.gpkg"
DESTINATION = ROOT / "outputs" / "gisborne" / "review" / "cards"
TILE_SIZE = 256
GDC_IMAGERY = (
    "https://tiles.arcgis.com/tiles/8G10QCd84QpdcTJ9/arcgis/rest/services/"
    "Imagery_satellite_gisborne_2024/MapServer"
)
ORIGIN_X = -4_020_900.0
ORIGIN_Y = 19_998_100.0
RESOLUTIONS = {
    0: 529.1677250021168,
    1: 264.5838625010584,
    2: 132.2919312505292,
    3: 52.91677250021167,
    4: 26.458386250105836,
    5: 13.229193125052918,
    6: 7.9375158750317505,
    7: 5.291677250021167,
    8: 2.6458386250105836,
    9: 1.9843789687579376,
    10: 1.3229193125052918,
    11: 0.5291677250021167,
}


def _global_pixel(x: float, y: float, level: int) -> tuple[float, float]:
    resolution = RESOLUTIONS[level]
    return (x - ORIGIN_X) / resolution, (ORIGIN_Y - y) / resolution


def _choose_level(bounds: tuple[float, float, float, float]) -> int:
    min_x, min_y, max_x, max_y = bounds
    for level in range(10, -1, -1):
        x0, y1 = _global_pixel(min_x, min_y, level)
        x1, y0 = _global_pixel(max_x, max_y, level)
        if abs(x1 - x0) <= 600 and abs(y1 - y0) <= 600:
            return level
    return 0


#: One 256 px aerial tile is tens of kilobytes; this only rules out a response
#: large enough to exhaust memory before PIL ever inspects it.
MAXIMUM_TILE_BYTES = 16 * 1024 * 1024
OVERVIEW_LEVELS_BELOW_DETAIL = 3
GDC_ATTRIBUTION = "Gisborne District Council satellite imagery 2024 (credited to LINZ)"


def _imagery_source() -> dict[str, object]:
    """Record the imagery service, its stated credit and the tiers used."""

    request = urllib.request.Request(f"{GDC_IMAGERY}?f=json", headers={"User-Agent": "nz-ets-screening/0.2"})
    with urllib.request.urlopen(request, timeout=60) as response:
        info = json.loads(response.read(MAXIMUM_TILE_BYTES))
    return {
        "service": GDC_IMAGERY,
        "copyright_text": info.get("copyrightText"),
        "description": info.get("description") or info.get("serviceDescription"),
        "retrieved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tile_grid_resolution_m": {str(level): value for level, value in RESOLUTIONS.items()},
        "note": "Tile-grid resolution is not the native imagery resolution.",
    }


def _tile(level: int, column: int, row: int) -> Image.Image:
    url = f"{GDC_IMAGERY}/tile/{level}/{row}/{column}"
    request = urllib.request.Request(url, headers={"User-Agent": "nz-ets-screening/0.2"})
    with urllib.request.urlopen(request, timeout=60) as response:
        declared = response.headers.get("Content-Length")
        if declared is not None and declared.isdigit() and int(declared) > MAXIMUM_TILE_BYTES:
            raise RuntimeError(f"tile {url} declares {declared} bytes")
        body = response.read(MAXIMUM_TILE_BYTES + 1)
    if len(body) > MAXIMUM_TILE_BYTES:
        raise RuntimeError(f"tile {url} exceeds the {MAXIMUM_TILE_BYTES} byte limit")
    with Image.open(io.BytesIO(body)) as image:
        return image.convert("RGB")


def _panel(geometry, level: int, centre: Point, *, mark_centre: bool = False) -> Image.Image:
    """Render an exact centred viewport, including all polygon hole outlines."""

    size = TILE_SIZE * 3
    centre_x, centre_y = _global_pixel(centre.x, centre.y, level)
    origin_x = math.floor(centre_x - size / 2)
    origin_y = math.floor(centre_y - size / 2)
    panel = Image.new("RGB", (size, size))
    for column in range(origin_x // TILE_SIZE, (origin_x + size - 1) // TILE_SIZE + 1):
        for tile_row in range(origin_y // TILE_SIZE, (origin_y + size - 1) // TILE_SIZE + 1):
            panel.paste(
                _tile(level, column, tile_row),
                (column * TILE_SIZE - origin_x, tile_row * TILE_SIZE - origin_y),
            )
    draw = ImageDraw.Draw(panel)
    polygons = list(geometry.geoms) if geometry.geom_type == "MultiPolygon" else [geometry]
    for polygon in polygons:
        for ring in [polygon.exterior, *polygon.interiors]:
            points = []
            for x, y in ring.coords:
                px, py = _global_pixel(x, y, level)
                points.append((px - origin_x, py - origin_y))
            draw.line(points, fill=(255, 45, 85), width=5, joint="curve")
    if mark_centre:
        x, y = centre_x - origin_x, centre_y - origin_y
        draw.line((x - 10, y, x + 10, y), fill=(255, 255, 0), width=3)
        draw.line((x, y - 10, x, y + 10), fill=(255, 255, 0), width=3)
    return panel


def _draw_card(row, attribution: str = GDC_ATTRIBUTION) -> Image.Image:
    geometry = row.geometry
    # The service advertises level 11, but coverage is incomplete. Level 10 is
    # the highest consistently available tier. Its tile grid is 1.32 m per
    # pixel, but that is the tiling, not the imagery: the 2024 satellite
    # mosaic appears to have a native pixel nearer 10 m, so small features
    # such as tracks are not resolvable. Check SOURCE.json before relying on it.
    detail_level = 10
    # A small unit fits at the detail level too, which made both panels
    # identical. Keep the overview at least 3 levels (about 4x) wider.
    overview_level = min(_choose_level(geometry.bounds), detail_level - OVERVIEW_LEVELS_BELOW_DETAIL)
    centre = geometry.representative_point()
    min_x, min_y, max_x, max_y = geometry.bounds
    overview_centre = Point((min_x + max_x) / 2, (min_y + max_y) / 2)
    overview = _panel(geometry, overview_level, overview_centre)
    detail = _panel(geometry, detail_level, centre, mark_centre=True)
    card = Image.new("RGB", (TILE_SIZE * 6, TILE_SIZE * 3))
    card.paste(overview, (0, 0))
    card.paste(detail, (TILE_SIZE * 3, 0))
    draw = ImageDraw.Draw(card)
    draw.line((TILE_SIZE * 3, 0, TILE_SIZE * 3, TILE_SIZE * 3), fill="white", width=4)
    caption = (
        f"{row.unit_id} | {row.lcdb_class} | OVERVIEW L{overview_level} / "
        f"DETAIL L{detail_level} at interior point"
    )
    font = ImageFont.load_default()
    draw.rectangle((0, 0, 1536, 34), fill=(0, 0, 0))
    draw.text((10, 9), caption, fill=(255, 255, 255), font=font)
    draw.rectangle((0, TILE_SIZE * 3 - 24, 1536, TILE_SIZE * 3), fill=(0, 0, 0))
    draw.text(
        (10, TILE_SIZE * 3 - 18),
        f"Screening / triage only - not an eligibility determination. Imagery: {attribution}",
        fill=(255, 255, 255),
        font=font,
    )
    return card


def _card_path(destination: Path, index: int, unit_id: str) -> Path:
    # IDs come from an external queue, so slashes and Windows path characters
    # must remain filename text rather than control the destination directory.
    safe_id = urllib.parse.quote(str(unit_id), safe="")
    return destination / f"{index:02d}_{safe_id}.jpg"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DESTINATION)
    parser.add_argument("--queue", type=Path, default=QUEUE)
    args = parser.parse_args()
    destination = args.output
    destination.mkdir(parents=True, exist_ok=True)
    queue = gpd.read_file(args.queue).to_crs(2193).sort_values("unit_id")
    if len(queue) != 30:
        raise RuntimeError(f"expected a 30-feature review queue, received {len(queue)}")
    queue["unit_id"] = validate_review_sample_ids(queue["unit_id"].tolist())
    source = _imagery_source()
    (destination / "SOURCE.json").write_text(json.dumps(source, indent=2), encoding="utf-8", newline="\n")
    attribution = source["copyright_text"] or GDC_ATTRIBUTION
    cards: list[Path] = []
    for index, (_, row) in enumerate(queue.iterrows(), start=1):
        path = _card_path(destination, index, row.unit_id)
        _draw_card(row, attribution).save(path, quality=88, optimize=True)
        cards.append(path)
        print(f"{index:02d}/30 {row.unit_id}")

    for sheet_index in range(3):
        sheet = Image.new("RGB", (1536 * 2, 768 * 5), "white")
        for slot, path in enumerate(cards[sheet_index * 10 : (sheet_index + 1) * 10]):
            with Image.open(path) as image:
                sheet.paste(image, ((slot % 2) * 1536, (slot // 2) * 768))
        sheet.save(destination / f"contact_sheet_{sheet_index + 1}.jpg", quality=82, optimize=True)


if __name__ == "__main__":
    main()
