# Pilot deployment (Kubernetes / OpenShift)

For the operators of a pilot. The chart is in [`infra/helm/nexira/`](../../infra/helm/nexira/). Backups are covered in [backup-restore.md](backup-restore.md), and the security position in [../security/asvs-l2.md](../security/asvs-l2.md).

A pilot runs with `APP_ENV=pilot`, which the chart sets. In that mode:
- there is no scenario API and no presenter bar (D-21);
- there are no interactive API docs;
- there is no demo seed: `nexira_sim.seed` and the fixtures refuse to run.

Phase 1 has only the simulated channel adapter, so nothing is sent by SMS, email or WhatsApp.

## What the chart deploys, and what it expects

| Component | Deployed by the chart | Notes |
|---|---|---|
| backend (API) | Deployment, 2 replicas, PDB | connects as `nexira_api` only (D-01) |
| worker | Deployment, 1 replica | same image, `python -m app.workers` |
| frontend (nginx) | Deployment, 2 replicas, PDB | unprivileged nginx on port 8080; CSP and HSTS |
| migrate | Helm hook Job (pre-install, pre-upgrade) | the only pod with the owner secret |
| backup | CronJob and PVC | the only pod with the `nexira_backup` secret |
| Redis | StatefulSet with AOF and a password (optional) | or bring your own: `redis.enabled=false` |
| PostgreSQL 16 + PostGIS 3 | **No: yours** | bootstrapped with `infra/postgres/init.sql` |
| Keycloak (IdP) | **No: yours** | the only external egress the API needs |
| LLM gateway (vLLM/Ollama) | **No: yours, optional** | `llm.provider=stub` makes no model calls |

Every pod runs:
- non-root, with a read-only root filesystem;
- with all capabilities dropped and the RuntimeDefault seccomp profile;
- with no service-account token.

This meets the restricted Pod Security Standard and OpenShift's `restricted-v2` SCC. Set `openshift: true` so that OpenShift chooses the UIDs.

## 1. Images

Build the images and push them to the registry the cluster pulls from. Mirror `redis:7.4-alpine` as well; there are no pulls from the internet at run time (NFR 1).

```sh
docker build -t $REG/nexira-backend:0.1.0 backend
docker build -t $REG/nexira-postgres:0.1.0 infra/postgres
docker build -t $REG/nexira-frontend:0.1.0 \
  --build-arg VITE_DEMO_MODE=false \
  --build-arg VITE_OIDC_URL=https://idp.example.internal \
  --build-arg VITE_OIDC_REALM=nexira \
  --build-arg VITE_OIDC_CLIENT_ID=nexira-web \
  frontend
```

The IdP settings are compiled into the frontend bundle, so each IdP needs its own frontend build. The chart mounts its own nginx config and headers, so the CSP comes from `oidc.publicOrigin`, not from the image. Keep `oidc.publicOrigin` the same as the origin of `VITE_OIDC_URL`.

## 2. Database

On your PostgreSQL 16 server, with the PostGIS 3 package installed, run the bootstrap once as the superuser:

```sh
psql -v ON_ERROR_STOP=1 -U postgres -d postgres \
  -v owner_password=... -v api_password=... -v backup_password=... -v db_name=nexira \
  -f infra/postgres/init.sql
```

`init.sql` includes `backup-role.sql`, so run it from the `infra/postgres` directory. It creates:
- `nexira_owner`, which owns the schema and runs migrations;
- `nexira_app` and `nexira_api`, the runtime roles, with no superuser rights and no BYPASSRLS;
- `nexira_backup`, which is read-only and can bypass RLS, for pg_dump only;
- the PostGIS and pgcrypto extensions.

Require TLS from clients (`hostssl` in `pg_hba.conf`). Then add `?ssl=require` to the asyncpg DSNs below.

## 3. Secrets (one per database user)

Keep these in your vault and sync them into the namespace, for example with External Secrets, Vault Agent or sealed secrets. Use the names in `secrets.existing`.

| Secret | Keys | Mounted by |
|---|---|---|
| `nexira-api` | `DATABASE_URL` = `postgresql+asyncpg://nexira_api:…@host:5432/nexira?ssl=require`, `REDIS_URL` = `redis://:…@<release>-redis:6379/0` | backend, worker |
| `nexira-db-owner` | `MIGRATIONS_DATABASE_URL` (`nexira_owner`) | migrate Job only |
| `nexira-db-backup` | `PGPASSWORD` (`nexira_backup`) | backup CronJob only |
| `nexira-redis` | `REDIS_PASSWORD` | the in-chart Redis only |

`secrets.create: true` makes the chart create these Secrets from values. Use it on throwaway test clusters only, because the passwords then sit in a values file.

## 4. Identity provider (Keycloak realm for the pilot)

The demo realm (`infra/keycloak/nexira-demo-realm.json`) is for local use only. The pilot realm must have:

- **MFA (OTP) required** for every user (D-04: required in the pilot realm). Make "Configure OTP" a default required action.
- Brute-force detection on, and a password policy (length ≥ 12, not the username, history).
- Client `nexira-web`:
  - public, standard flow with PKCE S256;
  - redirect URI and web origin set to the pilot host only;
  - **direct access grants off**.
- An audience mapper that puts `nexira-api` in the token's `aud` (`oidc.audience`).
- **No `nexira-dev-cli` client.** It allows the password grant, which only the local e2e tests use.
- Access token lifespan of 5 minutes or less, and an SSO idle timeout of 30 minutes or less, as in the demo realm.

**Roles.** Roles are not read from the token (D-04). Users get roles from the `user_role` table. Phase 1 has no admin screen for this, so the first admin and every role grant are inserted with SQL as `nexira_owner`, with the tenant set. That step needs its own runbook (see the gaps in the ASVS list).

## 5. Values and install

Start from `infra/helm/nexira/values.yaml`. `ci/pilot-values.yaml` and `ci/openshift-values.yaml` are worked examples. At minimum, set:
- `imageRegistry`;
- `database.host` and `database.egress`;
- `oidc.issuer`, `oidc.jwksUrl`, `oidc.publicOrigin` and `oidc.egress`;
- `app.workerTenantIds`;
- `frontend.tiles.existingClaim`;
- `ingress.*` or `route.*`;
- `networkPolicy.ingressFrom` and `networkPolicy.dns`;
- `backup.storageClass`, which should be an encrypted class.

```sh
helm upgrade --install nexira infra/helm/nexira -n nexira -f pilot-values.yaml
```

The chart refuses to render if a required setting is missing, for example:
- no database or IdP egress peer;
- an Ingress without a TLS Secret.

## 6. Network

- **Default-deny.** A NetworkPolicy blocks all ingress and egress for the release's pods. The allowed paths are:
  - frontend: from `networkPolicy.ingressFrom`, to the backend;
  - backend: from the frontend, to PostgreSQL, Redis, the IdP (`oidc.egress`) and the LLM gateway (only when `llm.provider` is not `stub`);
  - worker: to PostgreSQL, Redis and the LLM gateway;
  - migrate and backup: to PostgreSQL;
  - all of them: to cluster DNS.
- **No other egress.** There is none to the internet. The browser talks to the IdP directly; that traffic is not cluster egress.
- **Install order.** The migrate Job is a pre-install hook, so on the very first install it runs before the policies exist. From then on the `db-jobs` policy covers it.
- **TLS 1.3 (NFR 2).** TLS terminates at the ingress or route:
  - ingress-nginx: set `ssl-protocols: "TLSv1.3"` in the controller ConfigMap;
  - OpenShift: use the `Modern` TLS security profile on the IngressController.
- **Inside the cluster.** Traffic between the pods is plain HTTP. Use a service mesh with mTLS if your policy requires encryption inside the cluster (see the gap list).

## 7. After install

1. `kubectl get pods`: everything is Running, and the migrate Job has Completed.
2. Sign in as the first admin (with MFA). Then open Audit and run **Verify**; the chain should be intact.
3. Run a restore test from the backup PVC. See [backup-restore.md](backup-restore.md).
4. Check that egress is blocked. From a backend pod, `python -c "import urllib.request; urllib.request.urlopen('https://example.com', timeout=5)"` must fail.

## Validation done in Prompt 16

- **`make helm-check`.** `helm lint --strict`, `helm template` and kubeconform (Kubernetes 1.30 schemas, strict) pass for both `ci/pilot-values.yaml` and `ci/openshift-values.yaml`. The OpenShift Route is skipped, because kubeconform has no schema for it. CI runs the same check.
- **Not yet tested on a cluster.** The chart has **not** been installed on a real Kubernetes or OpenShift cluster. Do that in a staging namespace before the pilot.
