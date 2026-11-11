#!/usr/bin/env python3
"""The gazetteer for map search: frontend/src/map/places.json.

Built once from Natural Earth's 1:10m populated places (simple), which is in the public domain.
The result is committed; the running app never fetches it, and a search sends nothing anywhere
(SRC-03, D-24).

Source: https://naciscdn.org/naturalearth/10m/cultural/ne_10m_populated_places_simple.zip
(Natural Earth 5.1.1), SHA-256 below. Read with the standard library: the zip's .dbf table.

    python3 infra/scripts/build-places.py ne_10m_populated_places_simple.zip

Each place is [name, ascii name or "" when the same, region, ISO country, lon, lat, rank], with
the position rounded to 0.001 degree and rank the population rank (0-14), most populous first.
"""

import hashlib
import json
import struct
import sys
import zipfile
from pathlib import Path

SHA256 = "2963ee08f7743f13f37d5243acd77a2f7a510e26a36c7e04b920f1b381f2b251"
TABLE = "ne_10m_populated_places_simple.dbf"
OUT = Path(__file__).resolve().parents[2] / "frontend" / "src" / "map" / "places.json"


def records(raw: bytes) -> list[dict[str, str]]:
    """A dBase III table: a 32-byte header, 32-byte field descriptors, then fixed-width rows."""
    count, header, length = struct.unpack("<4xIHH", raw[:12])
    fields: list[tuple[str, int]] = []
    at = 32
    while raw[at] != 0x0D:
        fields.append((raw[at : at + 11].split(b"\0")[0].decode("ascii"), raw[at + 16]))
        at += 32
    rows = []
    for n in range(count):
        row = raw[header + n * length : header + (n + 1) * length]
        if row[:1] == b"*":
            continue  # deleted
        values, offset = {}, 1
        for name, width in fields:
            values[name] = row[offset : offset + width].decode("utf-8", "replace").strip()
            offset += width
        rows.append(values)
    return rows


def main(path: str) -> None:
    raw = Path(path).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != SHA256:
        sys.exit(f"build-places: {path} has SHA-256 {digest}, expected {SHA256}")
    with zipfile.ZipFile(path) as z:
        rows = records(z.read(TABLE))
    places = []
    for r in rows:
        name, ascii_name = r["name"], r["nameascii"]
        places.append(
            [
                name,
                "" if ascii_name == name else ascii_name,
                r["adm1name"],
                r["iso_a2"] if len(r["iso_a2"]) == 2 and r["iso_a2"] != "-9" else "",
                round(float(r["longitude"]), 3),
                round(float(r["latitude"]), 3),
                int(float(r["rank_max"] or 0)),
            ]
        )
    places.sort(key=lambda p: (-p[6], p[0]))
    OUT.write_text(json.dumps(places, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"build-places: {len(places)} places to {OUT}")


if __name__ == "__main__":
    main(sys.argv[1])
