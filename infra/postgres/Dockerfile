# Same as docs/schema/checks/Dockerfile.postgres: official postgres:16 with the
# PostGIS 3 package, which has a native arm64 build (postgis/postgis:16-3.4 does not).
FROM postgres:16-bookworm
RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-16-postgis-3 \
 && rm -rf /var/lib/apt/lists/*
COPY init.sql /nexira/init.sql
COPY 00-nexira-init.sh /docker-entrypoint-initdb.d/00-nexira-init.sh
