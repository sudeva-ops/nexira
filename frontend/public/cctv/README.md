# CCTV clips for the Site Twin (simulated)

The Site Twin's CCTV wall (`src/screens/twin/CctvWall.tsx`) plays one looped, muted clip per
zone kind from this folder, served by the app itself (no external URL at runtime, D-24). A
camera starts at its own point in the loop, and a zone's second camera is mirrored, so the
wall looks live. A zone kind without a clip shows a generated view instead.

| File | Shown on |
|---|---|
| `gate.mp4` | the gates (a gate or barrier and its forecourt) |
| `lobby.mp4` | lobby and reception |
| `consular.mp4` | the consular hall (a counter or waiting area) |
| `office.mp4` | chancery offices |
| `conference.mp4` | the conference room |
| `comms.mp4` | the comms / IT room (server racks) |
| `safe-room.mp4` | the safe room |
| `suite.mp4` | the ambassador's suite |
| `muster.mp4` | the muster point (a courtyard or car park) |

Each clip:
- **no people**, or none who can be recognised: no real personal data (AGENTS.md);
- **a licence that allows it here**: this repository is public, so the clip is redistributed;
  record its source and licence below;
- about 10 s, 1280×720 or smaller, H.264 MP4, no audio track, under 3 MB
  (`ffmpeg -i in.mp4 -t 10 -an -vf scale=1280:-2 -c:v libx264 -crf 28 -movflags +faststart gate.mp4`).

## Sources and licences

| File | Source | Licence |
|---|---|---|
