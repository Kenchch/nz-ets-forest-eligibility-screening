"""Verify pinned demonstration inputs without platform-specific shell tools."""

from hashlib import sha256
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    manifest = ROOT / "data" / "checksums.sha256"
    for raw in manifest.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        expected, relative = line.split(maxsplit=1)
        path = ROOT / "data" / relative
        actual = sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise SystemExit(f"checksum mismatch: {relative}: {actual} != {expected}")
        print(f"ok  {relative}")


if __name__ == "__main__":
    main()

