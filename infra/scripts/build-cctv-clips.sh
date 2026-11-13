#!/usr/bin/env bash
# The Site Twin's CCTV clips (TWN-03, simulated), built into frontend/public/cctv/ (git-ignored).
#
# Nine free stock clips from Pexels (https://www.pexels.com/license/: free to
# use and modify, no attribution required; not to be redistributed on other stock sites or sold
# unaltered). Each is trimmed, re-timed and made into a seamless loop, so what the app serves
# is altered; and the files stay out of git, so this public repository never redistributes
# them. Three clips show people, only from behind or from far away, so that no face can be made
# out (TWN-17, D-57): the gates, the lobby and the offices. Every frame of those loops was
# checked by eye; check again before changing a row. The other six are empty places: no
# suitable clip was found for the consular hall, the conference room or the muster point. The running app never fetches them from the internet: the
# frontend image serves them (D-24). Without them the CCTV wall draws generated views.
#
#   make cctv-clips          # download (checked against SHA-256), then build the loops
#   FORCE=1 make cctv-clips  # rebuild loops that already exist
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="$ROOT/frontend/public/cctv"
CACHE="$ROOT/infra/cctv-cache"
mkdir -p "$OUT" "$CACHE"
command -v ffmpeg >/dev/null || { echo "cctv-clips: needs ffmpeg" >&2; exit 1; }

sha256() { if command -v sha256sum >/dev/null; then sha256sum "$1"; else shasum -a 256 "$1"; fi | cut -d' ' -f1; }

# name | Pexels id | file | SHA-256 | start s | length s | slow-down | mode | author
# mode: loop     a static camera; the last second cross-fades into the first
#       sweep    a slow pan, played forward then back, as a patrolling PTZ camera
CLIPS=(
  "gate|5899392|5899392-hd_1280_720_24fps.mp4|f9a186fa09e3b1228aa6990528cc50957d6ba9c824205f74ac2da9ef48e57558|1|10|1|loop|RDNE Stock project"
  "lobby|10868348|10868348-hd_1280_720_30fps.mp4|9bf7af548092de3d09b21dac9419a8688f48fe710bbabda2a0e4ba0246f6a1ed|0|10|1|loop|see the Pexels page"
  "consular|5203514|5203514-hd_1280_720_60fps.mp4|465b23a19af9be00275c607602926561ea6c71c875f55d634468e212d31b9cc1|0|2.8|2.5|sweep|Enrique Silva"
  "office|11903990|11903990-hd_1280_720_25fps.mp4|35d5215a60fc8454c29f10e4a6cfe55d1d47882d9765c6226b8e03bddb6ab68f|5.8|10|1|loop|see the Pexels page"
  "conference|5716999|5716999-hd_1280_720_25fps.mp4|3d07f77e0d8894c43218b95b612b49e0d03c1ffd07e5b620999dcf8274fb3df4|2|8|1|sweep|Tima Miroshnichenko"
  "comms|5028622|5028622-hd_1280_720_25fps.mp4|6f21f24a028347ae3b2c1d872b71f88ff3abdf734eadaf122ec901add3f0664d|4|6|1.3|sweep|ALL IZ Well"
  "safe-room|19217894|19217894-hd_1280_720_30fps.mp4|8c1bdb25627ba7f98db18ce3a6f3626fa50e0b95812457b40452488282ab3b7f|0|9.5|1|sweep|Nino Souza"
  "suite|7507165|7507165-hd_1366_720_25fps.mp4|76bf97c365e55091fc0f81915d0b69d54efdc86720e96a03f52a75caacdb6ef2|2|10|1|loop|cottonbro studio"
  "muster|5705255|5705255-hd_1280_720_30fps.mp4|cac7262c033f97c8dd666509fe907e128603881fd788e0b720317a7dd8464d87|2|10|1|loop|Pavel Danilyuk"
)

# 1280×720 at 25 fps, H.264, no audio, each under 3 MB for a wall of tiles.
FINISH="scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,fps=25,format=yuv420p"
# The bitrate cap keeps sunlit foliage small, and looks like a camera's compression anyway.
ENCODE=(-an -c:v libx264 -preset slow -crf 27 -maxrate 1.5M -bufsize 3M -movflags +faststart)

CREDITS="$OUT/CREDITS.md"
{
  echo "# CCTV clips: sources (built by infra/scripts/build-cctv-clips.sh; not in git)"
  echo
  echo "Free stock video from Pexels, used under the Pexels licence (https://www.pexels.com/license/), trimmed and looped."
  echo
  echo "| File | Pexels video | Author |"
  echo "|---|---|---|"
} >"$CREDITS"

for row in "${CLIPS[@]}"; do
  IFS='|' read -r name id file sha start len slow mode author <<<"$row"
  echo "| $name.mp4 | https://www.pexels.com/video/$id/ | $author |" >>"$CREDITS"
  out="$OUT/$name.mp4"
  if [ -s "$out" ] && [ -z "${FORCE:-}" ]; then
    echo "cctv-clips: $name.mp4 exists"
    continue
  fi
  src="$CACHE/$id.mp4"
  if [ ! -s "$src" ] || [ "$(sha256 "$src")" != "$sha" ]; then
    echo "cctv-clips: downloading Pexels $id ($author)"
    curl -fsSL -A "Mozilla/5.0" -o "$src.part" "https://videos.pexels.com/video-files/$id/$file"
    got="$(sha256 "$src.part")"
    if [ "$got" != "$sha" ]; then
      rm -f "$src.part"
      echo "cctv-clips: Pexels $id checksum mismatch ($got); not used" >&2
      exit 1
    fi
    mv "$src.part" "$src"
  fi
  if [ "$mode" = loop ]; then
    fade=1
    total=$(awk "BEGIN{print $len+$fade}")
    # Play from 1 s in to the end, cross-fading the last second into the opening second, which
    # ends exactly where the loop starts: no seam.
    ffmpeg -loglevel error -y -ss "$start" -t "$total" -i "$src" -filter_complex \
      "[0:v]$FINISH,split[a][b];[a]trim=$fade:$total,setpts=PTS-STARTPTS[body];[b]trim=0:$fade,setpts=PTS-STARTPTS[head];[body][head]xfade=transition=fade:duration=$fade:offset=$(awk "BEGIN{print $len-$fade}")[v]" \
      -map "[v]" "${ENCODE[@]}" "$out"
  else
    ffmpeg -loglevel error -y -ss "$start" -t "$len" -i "$src" -filter_complex \
      "[0:v]setpts=$slow*PTS,$FINISH,split[f][r];[r]reverse[b];[f][b]concat=n=2:v=1:a=0[v]" \
      -map "[v]" "${ENCODE[@]}" "$out"
  fi
  echo "cctv-clips: $name.mp4 ($mode, $(du -h "$out" | cut -f1))"
done
echo "cctv-clips: done; rebuild the frontend image to serve them (make up)"
