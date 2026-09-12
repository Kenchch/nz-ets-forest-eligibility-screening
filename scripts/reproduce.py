"""Rebuild the committed demonstration and ArcGIS reference layout."""

from pathlib import Path
import shutil

from ets_screening.demo_data import build_demo_layers
from ets_screening.screen import run_screening


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    candidates, pre1990, conservation = build_demo_layers()
    manifest = run_screening(
        candidates,
        pre1990,
        conservation,
        ROOT / "outputs",
        reject_rate_threshold=0.90,
    )
    shutil.copy2(ROOT / "outputs" / "layout_map.pdf", ROOT / "arcgis" / "layout_map.pdf")
    print(manifest)


if __name__ == "__main__":
    main()

