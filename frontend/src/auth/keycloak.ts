import Keycloak from "keycloak-js";

// OIDC login (D-04). The token is used only to call the API; the UI never reads
// roles from it. Roles come from GET /api/me.
/** The IdP's URL: absolute, or a path on the app's own origin ("/auth"), so one built image
 * works at any address (docs/plan-demo-codespaces.md §2). */
export function oidcUrl(configured: string | undefined, origin: string): string {
  const url = configured ?? "http://localhost:8080";
  return url.startsWith("/") ? new URL(url, origin).toString().replace(/\/$/, "") : url;
}

const keycloak = new Keycloak({
  url: oidcUrl(import.meta.env.VITE_OIDC_URL, window.location.origin),
  realm: import.meta.env.VITE_OIDC_REALM ?? "nexira-demo",
  clientId: import.meta.env.VITE_OIDC_CLIENT_ID ?? "nexira-web",
});

export async function initAuth(): Promise<void> {
  await keycloak.init({
    onLoad: "login-required",
    pkceMethod: "S256",
    checkLoginIframe: false,
  });
}

/** A token valid for at least 30 more seconds, refreshed when needed. */
export async function getToken(): Promise<string> {
  await keycloak.updateToken(30);
  if (!keycloak.token) throw new Error("not authenticated");
  return keycloak.token;
}

export function logout(): Promise<void> {
  return keycloak.logout({ redirectUri: window.location.origin });
}
