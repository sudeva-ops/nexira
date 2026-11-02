# The demo's frontend (docs/plan-demo-codespaces.md §2, PR 2): the frontend image built with
# VITE_DEMO_MODE=true and VITE_OIDC_URL=/auth, plus the self-hosted map tiles (D-24) that
# docker-compose.yml mounts at /srv/tiles locally. Context: the repository root, after
# `make tiles`.
ARG BASE
FROM ${BASE}
COPY --chown=101:0 infra/tiles/world.pmtiles infra/tiles/nairobi.pmtiles infra/tiles/BUILD.txt /srv/tiles/
COPY --chown=101:0 infra/tiles/fonts /srv/tiles/fonts
COPY --chown=101:0 infra/tiles/sprites /srv/tiles/sprites
