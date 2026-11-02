# Plan · Private demo in GitHub Codespaces (Option A)

For the product owner and the coding agent. Goal: let invited people run the NEXIRA demo themselves, privately, without a server and without tunnelling from a laptop, and without seeing the source code. Everything in the demo is simulated (D-19). Items marked **needs a decision** wait for the product owner.

## 1. How guests use it

1. The product owner gives a guest read access to a new private repository, **`sudeva-ops/nexira-demo`**. It holds no source code: only the codespace configuration, a compose file that pulls pre-built images, a start-up script and a guest guide.
2. The guest opens it on GitHub and clicks **Code → Create codespace**. The machine type is set to 4 cores and 16 GB.
3. The codespace pulls the images, starts the stack, seeds the demo and opens NEXIRA in the browser, all in about 5 minutes on the first start.
4. The address is a private forwarded port (`https://<codespace>-3000.app.github.dev`). Only that guest, signed in to GitHub, can open it.
5. The terminal and a `WELCOME.md` show the demo users and a password generated for that codespace. The presenter bar and `make`-style commands (`demo reset`) work as they do locally.
6. Each guest has their own copy: nothing they do affects anyone else. A codespace stops after 30 minutes idle and can be restarted or deleted.

## 2. Changes in this repository (PR 1 and PR 2)

### PR 1 · The stack at any address (local behaviour unchanged)

| Today | Change |
|---|---|
| The browser reaches Keycloak directly on `localhost:8080` | The frontend's nginx proxies `/auth/` to Keycloak (`KC_HTTP_RELATIVE_PATH=/auth`, `KC_PROXY_HEADERS=xforwarded`), so the app, API, WebSocket and login share **one origin**. In Codespaces, private ports block cross-port calls, so this is required. |
| `VITE_OIDC_URL` is an absolute URL fixed at build time | It may also be a **relative path** (`/auth`), resolved against `window.location.origin` in `src/auth/keycloak.ts`. One pre-built image works at any address. The Dockerfile's CSP step leaves the IdP origin empty when the URL is relative (the CSP is then `'self'` only, which is stricter). |
| `KC_HOSTNAME` is `http://localhost:8080` | It is set from `NEXIRA_PUBLIC_ORIGIN` (default unchanged). |
| The realm allows redirects to `localhost:3000` and `5173` only | The realm import also allows `${NEXIRA_PUBLIC_ORIGIN}/*`. Keycloak substitutes environment placeholders on import, as it already does for `${DEMO_USER_PASSWORD}`; the default keeps localhost. |
| `OIDC_ISSUER` comes from `.env` | Unchanged mechanism; the demo sets it to `<public origin>/auth/realms/nexira-demo` for the backend and the seed (the tenant is found by issuer, D-04). |

- **Local development:** the defaults stay as today (`localhost`), and `make acceptance` must still pass, with a new compose profile or override that exercises `/auth`.
- **Review:** this touches the login set-up and the security headers. They are not on the D-29 list, but **an independent review runs anyway**, and the named sign-off is asked for. **Needs a decision:** treat as 🔒? Proposed: yes.

### PR 2 · Private images on GitHub Packages

- A workflow (`.github/workflows/demo-images.yml`) on a manual trigger and on tags `demo-*` builds and pushes to **ghcr.io/sudeva-ops/** (private):
  - `nexira-postgres`;
  - `nexira-backend` (API, worker and migrations);
  - `nexira-frontend` (`VITE_DEMO_MODE=true`, `VITE_OIDC_URL=/auth`, the 139 MB map tiles copied in);
  - `nexira-seed` (simulator and seed);
  - `nexira-keycloak` (Keycloak 26.4 with the realm file).
- Each package is private and grants **Codespaces access to `nexira-demo` only** (a GitHub package setting), so a guest's codespace can pull it without any token.
- The images contain the compiled app, not the repository. Like any container image, a determined guest could inspect the image layers (the Python backend is source inside the image). **Needs a decision:** acceptable for invited evaluators? Proposed: yes, with a short confidentiality note in the guest guide. Fully hiding the code would need a hosted demo instead.

## 3. The demo repository (PR 3, created only after approval)

`sudeva-ops/nexira-demo`, private:
- `.devcontainer/devcontainer.json`: Docker-in-Docker; 4 cores, 16 GB; port 3000 forwarded as **private** and opened in the browser; the other ports not forwarded.
- `compose.yml`: the published images; no build.
- `scripts/start.sh` (on codespace start):
  - work out `NEXIRA_PUBLIC_ORIGIN` from `CODESPACE_NAME` and `GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN`;
  - generate random passwords (database roles, Keycloak admin, the demo users) into a local `.env` that never leaves the codespace;
  - pull the images, start the stack, migrate and seed;
  - print the URL, the demo users and the password.
- `scripts/demo` with `reset` (drop and reseed, as `make reset-demo`), `status` and `logs`.
- `README.md` and `WELCOME.md`: the guest guide (what NEXIRA is, the scenarios to play, the users and roles, "all data is simulated", how to stop and delete the codespace, cost).
- **Not in it:** any source code, real data or secrets.

## 4. Cost and access (needs a decision)

| Question | Proposed |
|---|---|
| Who pays for the codespaces? | The guest's own personal Codespaces allowance (free accounts: 120 core-hours a month, about 30 hours on 4 cores). An organisation that pays centrally can be set up later. |
| Who gets access? | The product owner adds each guest as a read collaborator on `nexira-demo`, and removes them afterwards. |
| The LLM | The built-in stub (no GPU in Codespaces); the guide says so. |
| Image updates | The product owner runs the workflow (or tags `demo-*`); new codespaces get the new images. |

## 5. Acceptance

- `make acceptance` still passes locally (14 specs), with the defaults.
- A new compose override `infra/docker-compose.public.yml` (one origin under `/auth`) passes a smoke spec locally: sign in, Decision Queue, a scenario scene, Site Twin.
- After PR 3, **a real codespace** created from `nexira-demo` (by the product owner, or by the agent if `gh` has the `codespace` scope) starts, seeds and passes the same smoke check through the private forwarded URL. The real output is reported.

## 6. PRs

1. The stack at any address (review; sign-off proposed).
2. Private images and the workflow.
3. The `nexira-demo` repository (created only after the product owner confirms).
