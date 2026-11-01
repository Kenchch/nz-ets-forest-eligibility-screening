"""Verify every pinned test and processed input without shell-specific tools."""

from hashlib import sha256
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    data = (ROOT / "data").resolve()
    manifest = data / "checksums.sha256"
    entries: list[tuple[str, str, Path]] = []
    seen: set[Path] = set()
    for line_number, raw in enumerate(manifest.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split(maxsplit=1)
        if len(fields) != 2 or not re.fullmatch(r"[0-9a-fA-F]{64}", fields[0]):
            raise SystemExit(f"invalid checksum entry on line {line_number}")
        expected, relative = fields
        path = (data / relative).resolve()
        if not path.is_relative_to(data) or path == data:
            raise SystemExit(f"checksum path is outside the data directory: {relative}")
        if path in seen:
            raise SystemExit(f"duplicate checksum entry: {relative}")
        seen.add(path)
        entries.append((expected.lower(), relative, path))
    if not entries:
        raise SystemExit("checksum manifest contains no pinned inputs")
    for expected, relative, path in entries:
        digest = sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        actual = digest.hexdigest()
        if actual != expected:
            raise SystemExit(f"checksum mismatch: {relative}: {actual} != {expected}")
        print(f"ok  {relative}")


if __name__ == "__main__":
    main()
