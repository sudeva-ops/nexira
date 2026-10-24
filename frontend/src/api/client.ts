export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

type TokenProvider = () => Promise<string>;

let tokenProvider: TokenProvider = () => Promise.reject(new Error("no token provider set"));

/** main.tsx wires this to Keycloak; tests use a fake. */
export function setTokenProvider(provider: TokenProvider): void {
  tokenProvider = provider;
}

/** The current access token, refreshed when needed (also used by the WebSocket). */
export function getAccessToken(): Promise<string> {
  return tokenProvider();
}

export async function apiGet<T>(path: string, params?: Record<string, string | number>): Promise<T> {
  const query = params
    ? "?" + new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)])).toString()
    : "";
  const response = await fetch(`${path}${query}`, {
    headers: { Authorization: `Bearer ${await tokenProvider()}`, Accept: "application/json" },
  });
  if (!response.ok) {
    throw new ApiError(response.status, `${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

export async function apiSend<T>(
  method: "POST" | "PATCH",
  path: string,
  body: unknown,
): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: {
      Authorization: `Bearer ${await tokenProvider()}`,
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const json = (await response.json()) as { detail?: unknown };
      if (typeof json.detail === "string") detail = json.detail;
    } catch {
      // keep the status text
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}
