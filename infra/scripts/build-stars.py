#!/usr/bin/env python3
"""The star field behind the world globe: frontend/src/map/stars.json.

Built once from the Yale Bright Star Catalogue, 5th revised edition (Hoffleit & Warren 1991),
which is in the public domain. The result is committed; the running app never fetches it (D-24).

Source: http://tdc-www.harvard.edu/catalogs/bsc5.dat.gz (the same records as CDS V/50),
SHA-256 below. Each record is 197 bytes: J2000 RA in bytes 76-83, Dec in 84-90, V magnitude in
103-107.

    python3 infra/scripts/build-stars.py bsc5.dat.gz

Kept: stars of magnitude 5.5 or brighter with a J2000 position (about 2,900), as
[ra_deg, dec_deg, magnitude], rounded to 0.01 degree and 0.1 magnitude, brightest first.
"""

import gzip
import hashlib
import json
import sys
from pathlib import Path

SHA256 = "0471ced07fc241e625613baa689b2fa5f4b59fd733f731003e57d2d436036cdb"
LIMIT = 5.5
OUT = Path(__file__).resolve().parents[2] / "frontend" / "src" / "map" / "stars.json"


def parse(line: str) -> list[float] | None:
    ra_h, ra_m, ra_s = line[75:77], line[77:79], line[79:83]
    sign, de_d, de_m, de_s = line[83], line[84:86], line[86:88], line[88:90]
    mag = line[102:107]
    if not ra_h.strip() or not mag.strip():
        return None  # no J2000 position: novae and objects later found not to be stars
    v = float(mag)
    if v > LIMIT:
        return None
    ra = 15 * (int(ra_h) + int(ra_m) / 60 + float(ra_s) / 3600)
    dec = int(de_d) + int(de_m) / 60 + int(de_s) / 3600
    return [round(ra, 2), round(-dec if sign == "-" else dec, 2), round(v, 1)]


def main(path: str) -> None:
    raw = Path(path).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != SHA256:
        sys.exit(f"build-stars: {path} has SHA-256 {digest}, expected {SHA256}")
    lines = gzip.decompress(raw).decode("ascii").splitlines()
    stars = sorted((s for s in map(parse, lines) if s), key=lambda s: s[2])
    OUT.write_text(json.dumps(stars, separators=(",", ":")) + "\n")
    print(f"build-stars: {len(stars)} stars to {OUT}")


if __name__ == "__main__":
    main(sys.argv[1])
