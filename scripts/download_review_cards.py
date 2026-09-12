"""Download 30 fixed-seed LINZ aerial review cards for the Gisborne queue."""

from __future__ import annotations

import io
import argparse
import urllib.request
from pathlib import Path

import geopandas as gpd
from PIL import Image, ImageDraw, ImageFont


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


def _tile(level: int, column: int, row: int) -> Image.Image:
    url = f"{GDC_IMAGERY}/tile/{level}/{row}/{column}"
    request = urllib.request.Request(url, headers={"User-Agent": "nz-ets-screening/0.2"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return Image.open(io.BytesIO(response.read())).convert("RGB")


def _draw_card(row) -> Image.Image:
    geometry = row.geometry
    level = _choose_level(geometry.bounds)
    centre = geometry.centroid
    centre_x, centre_y = _global_pixel(centre.x, centre.y, level)
    tile_column = int(centre_x // TILE_SIZE)
    tile_row = int(centre_y // TILE_SIZE)
    origin_x = (tile_column - 1) * TILE_SIZE
    origin_y = (tile_row - 1) * TILE_SIZE
    mosaic = Image.new("RGB", (TILE_SIZE * 3, TILE_SIZE * 3))
    for offset_x, column in enumerate(range(tile_column - 1, tile_column + 2)):
        for offset_y, tile_row_value in enumerate(range(tile_row - 1, tile_row + 2)):
            mosaic.paste(
                _tile(level, column, tile_row_value),
                (offset_x * TILE_SIZE, offset_y * TILE_SIZE),
            )

    draw = ImageDraw.Draw(mosaic)
    polygons = list(geometry.geoms) if geometry.geom_type == "MultiPolygon" else [geometry]
    for polygon in polygons:
        points = []
        for x, y in polygon.exterior.coords:
            px, py = _global_pixel(x, y, level)
            points.append((px - origin_x, py - origin_y))
        draw.line(points, fill=(255, 45, 85), width=5, joint="curve")
    caption = f"{row.parcel_id} | {row.lcdb_class} | imagery level {level}"
    draw.rectangle((0, 0, 768, 34), fill=(0, 0, 0))
    draw.text((10, 9), caption, fill=(255, 255, 255), font=ImageFont.load_default())
    return mosaic


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DESTINATION)
    parser.add_argument("--queue", type=Path, default=QUEUE)
    args = parser.parse_args()
    destination = args.output
    destination.mkdir(parents=True, exist_ok=True)
    queue = gpd.read_file(args.queue).to_crs(2193).sort_values("parcel_id")
    if len(queue) != 30:
        raise RuntimeError(f"expected a 30-feature review queue, received {len(queue)}")
    cards: list[Path] = []
    for index, (_, row) in enumerate(queue.iterrows(), start=1):
        path = destination / f"{index:02d}_{row.parcel_id}.jpg"
        _draw_card(row).save(path, quality=88, optimize=True)
        cards.append(path)
        print(f"{index:02d}/30 {row.parcel_id}")

    for sheet_index in range(3):
        sheet = Image.new("RGB", (768 * 2, 768 * 5), "white")
        for slot, path in enumerate(cards[sheet_index * 10 : (sheet_index + 1) * 10]):
            image = Image.open(path)
            sheet.paste(image, ((slot % 2) * 768, (slot // 2) * 768))
        sheet.save(destination / f"contact_sheet_{sheet_index + 1}.jpg", quality=82, optimize=True)


if __name__ == "__main__":
    main()
