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
