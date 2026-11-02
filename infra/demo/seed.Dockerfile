# The demo's seed job (docs/plan-demo-codespaces.md §2, PR 2): the simulator, which loads the
# fictional demo world through the backend's service layer (plan Q10). Context: the repository
# root. Runs `python -m nexira_sim.seed` with DATABASE_URL, MIGRATIONS_DATABASE_URL (the owner
# DSN, to create the tenant row), OIDC_ISSUER and DEMO_USER_PASSWORD, as `make seed` does.
FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

COPY backend /srv/backend
COPY simulator /srv/simulator
# The seed reads the demo users from the realm file (simulator/nexira_sim/seed/identities.py).
COPY infra/keycloak/nexira-demo-realm.json /srv/infra/keycloak/nexira-demo-realm.json
WORKDIR /srv/simulator
RUN rm -rf /srv/backend/.venv /srv/simulator/.venv \
 && uv sync --frozen --no-dev \
 && useradd --system --uid 10001 nexira
USER 10001
CMD ["python", "-m", "nexira_sim.seed"]
