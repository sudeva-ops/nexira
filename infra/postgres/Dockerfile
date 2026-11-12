# Same as docs/schema/checks/Dockerfile.postgres: official postgres:16 with the
# PostGIS 3 package, which has a native arm64 build (postgis/postgis:16-3.4 does not).
# Pinned (2026-11-12): the base image by digest (PostgreSQL 16.15) and PostGIS to the build made
# for it. An unpinned install took 3.7.0+dfsg-1.pgdg12+2, built for 16.16, which fails to load on
# 16.15 ("undefined symbol: heap_datum_check"). Move both together, and check CREATE EXTENSION.
FROM postgres:16-bookworm@sha256:5264710be20f409750ac6dc4e5706dcef929c87e241605463f0f9aefa932a8d9
ARG POSTGIS_VERSION=3.7.0+dfsg-1.pgdg12+1
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      postgresql-16-postgis-3=${POSTGIS_VERSION} postgresql-16-postgis-3-scripts=${POSTGIS_VERSION} \
 && rm -rf /var/lib/apt/lists/*
COPY init.sql backup-role.sql backup-grants.sql /nexira/
COPY 00-nexira-init.sh /docker-entrypoint-initdb.d/00-nexira-init.sh
