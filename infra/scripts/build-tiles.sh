#!/usr/bin/env bash
# D-24: self-hosted map data for the Global Operations map, built into infra/tiles/.
#
#   world.pmtiles    Protomaps basemap, whole world, zoom 0-6
#   nairobi.pmtiles  Protomaps basemap, Nairobi area, zoom 0-15
#   fonts/, sprites/ glyphs and sprites for the dark style (protomaps/basemaps-assets)
#
# This is the only step that downloads map data (approved at build time, plan Q3).
# The running app never fetches tiles, fonts or sprites from the internet.
#
#   TILES_BUILD=20261020 make tiles   # pin a Protomaps daily build (default: the latest)
#   FORCE=1 make tiles                # rebuild files that already exist
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="$ROOT/infra/tiles"
BIN="$OUT/.bin"
mkdir -p "$OUT" "$BIN"

PMTILES_VERSION=1.31.2
ASSETS_COMMIT=028c18f713baecad011301ff7a69acc39bcc2ae7  # protomaps/basemaps-assets
NAIROBI_BBOX="36.45,-1.65,37.20,-0.95"                 # west,south,east,north

# SHA-256 of the go-pmtiles release archives (recorded when this script was written;
# the release publishes no checksum file).
case "$(uname -s)_$(uname -m)" in
  Darwin_arm64)  ARCHIVE=go-pmtiles-${PMTILES_VERSION}_Darwin_arm64.zip;    SHA=40528f7f616fcbf91207cd48c8fc023d213f6d86c0cbf1f748732803d1880f3d ;;
  Darwin_x86_64) ARCHIVE=go-pmtiles-${PMTILES_VERSION}_Darwin_x86_64.zip;   SHA=1f0dc02eee6c58312dd6c509faee1b5c32f0596568af1bf51f1b034e7a88a65b ;;
  Linux_aarch64|Linux_arm64)
                 ARCHIVE=go-pmtiles_${PMTILES_VERSION}_Linux_arm64.tar.gz;  SHA=f8bd47e7ea866863489cad588fbaf2f31f42e5821f7a03f009b3769f05801cb1 ;;
  Linux_x86_64)  ARCHIVE=go-pmtiles_${PMTILES_VERSION}_Linux_x86_64.tar.gz; SHA=3ed7dbf4ec2e6dfe5e25b6f70d1ffc932729f93c86db353bf514dd71010a312f ;;
  *) echo "tiles: unsupported platform $(uname -s) $(uname -m)" >&2; exit 1 ;;
esac

sha256() { if command -v sha256sum >/dev/null; then sha256sum "$1"; else shasum -a 256 "$1"; fi | cut -d' ' -f1; }

PMTILES="$BIN/pmtiles-$PMTILES_VERSION"
if [ ! -x "$PMTILES" ]; then
  echo "tiles: downloading pmtiles $PMTILES_VERSION"
  tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
  curl -fsSL -o "$tmp/$ARCHIVE" "https://github.com/protomaps/go-pmtiles/releases/download/v$PMTILES_VERSION/$ARCHIVE"
  if [ "$(sha256 "$tmp/$ARCHIVE")" != "$SHA" ]; then
    echo "tiles: checksum mismatch for $ARCHIVE" >&2; exit 1
  fi
  case "$ARCHIVE" in
    *.zip) unzip -q -o "$tmp/$ARCHIVE" pmtiles -d "$tmp" ;;
    *)     tar -xzf "$tmp/$ARCHIVE" -C "$tmp" pmtiles ;;
  esac
  install -m 0755 "$tmp/pmtiles" "$PMTILES"
fi

BUILD="${TILES_BUILD:-}"
if [ -z "$BUILD" ]; then
  BUILD="$(curl -fsSL https://build-metadata.protomaps.dev/builds.json \
    | python3 -c 'import json,sys; print(sorted(b["key"] for b in json.load(sys.stdin))[-1][:8])')"
fi
SOURCE="https://build.protomaps.com/$BUILD.pmtiles"

extract() {  # name, extra args...
  local name="$1"; shift
  if [ -s "$OUT/$name" ] && [ -z "${FORCE:-}" ]; then
    echo "tiles: $name exists (FORCE=1 to rebuild)"; return
  fi
  echo "tiles: extracting $name from build $BUILD"
  "$PMTILES" extract "$SOURCE" "$OUT/$name.tmp" "$@"
  mv "$OUT/$name.tmp" "$OUT/$name"
}
extract world.pmtiles --maxzoom=6
extract nairobi.pmtiles --maxzoom=15 --bbox="$NAIROBI_BBOX"

if [ ! -f "$OUT/fonts/.commit" ] || [ "$(cat "$OUT/fonts/.commit")" != "$ASSETS_COMMIT" ] || [ -n "${FORCE:-}" ]; then
  echo "tiles: downloading fonts and sprites ($ASSETS_COMMIT)"
  tmp_assets="$(mktemp -d)"
  curl -fsSL "https://codeload.github.com/protomaps/basemaps-assets/tar.gz/$ASSETS_COMMIT" \
    | tar -xz -C "$tmp_assets" --strip-components=1 \
        "basemaps-assets-$ASSETS_COMMIT/fonts/Noto Sans Regular" \
        "basemaps-assets-$ASSETS_COMMIT/fonts/Noto Sans Medium" \
        "basemaps-assets-$ASSETS_COMMIT/fonts/Noto Sans Italic" \
        "basemaps-assets-$ASSETS_COMMIT/sprites/v4"
  rm -rf "$OUT/fonts" "$OUT/sprites"
  mv "$tmp_assets/fonts" "$OUT/fonts"
  mkdir -p "$OUT/sprites"
  mv "$tmp_assets/sprites/v4" "$OUT/sprites/v4"
  rm -rf "$tmp_assets"
  echo "$ASSETS_COMMIT" > "$OUT/fonts/.commit"
fi

cat > "$OUT/BUILD.txt" <<INFO
Protomaps build: $BUILD ($SOURCE)
pmtiles: $PMTILES_VERSION
basemaps-assets: $ASSETS_COMMIT
Built: $(date -u +%Y-%m-%dT%H:%M:%SZ)
Map data © OpenStreetMap contributors (ODbL). Basemap © Protomaps.
INFO
du -sh "$OUT"/world.pmtiles "$OUT"/nairobi.pmtiles "$OUT"/fonts "$OUT"/sprites
echo "tiles: done. Served by the frontend container at /tiles/."
