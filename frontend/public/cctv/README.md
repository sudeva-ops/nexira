# CCTV clips for the Site Twin (simulated)

The Site Twin's CCTV wall (`src/screens/twin/CctvWall.tsx`) plays one looped, muted clip per
zone kind from this folder, served by the app itself (no external URL at runtime, D-24). Cameras
sharing a clip start at evenly spaced points in its loop and are mirrored or framed tighter in
turn, so the wall looks live. A zone kind without a clip shows a generated view instead.

**Build them with `make cctv-clips`** (`infra/scripts/build-cctv-clips.sh`): nine free Pexels
stock clips of empty places, checked against SHA-256, trimmed and made into seamless loops
(static cameras cross-fade; panning ones sweep forward and back). The clips and the generated
`CREDITS.md` (each clip's source and author) are git-ignored: this public repository never
redistributes them. Rebuild the frontend image afterwards (`make up`).

| File | Shown on |
|---|---|
| `gate.mp4` | the gates |
| `lobby.mp4` | lobby and reception |
| `consular.mp4` | the consular hall |
| `office.mp4` | chancery offices |
| `conference.mp4` | the conference room |
| `comms.mp4` | the comms / IT room |
| `safe-room.mp4` | the safe room |
| `suite.mp4` | the ambassador's suite |
| `muster.mp4` | the muster point |

To change a clip, edit the script's table: no recognisable people (AGENTS.md: no real personal
data), a licence that allows use and modification, about 10 s, 1280×720, no audio, under 3 MB.
