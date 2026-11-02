# The demo's Keycloak (docs/plan-demo-codespaces.md §2, PR 2): the same version as
# docker-compose.yml, with the demo realm baked in (imported on first start; the passwords and
# the public origin are substituted from the environment). Context: the repository root.
FROM quay.io/keycloak/keycloak:26.4
COPY infra/keycloak/nexira-demo-realm.json /opt/keycloak/data/import/nexira-demo-realm.json
