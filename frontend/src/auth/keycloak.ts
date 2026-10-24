import Keycloak from "keycloak-js";

// OIDC login (D-04). The token is used only to call the API; the UI never reads
// roles from it. Roles come from GET /api/me.
const keycloak = new Keycloak({
  url: import.meta.env.VITE_OIDC_URL ?? "http://localhost:8080",
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
