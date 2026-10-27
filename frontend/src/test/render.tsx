import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

import { setTokenProvider } from "../api/client";
import type { Me } from "../api/me";
import { App } from "../app/App";

export const DUTY_OFFICER: Me = {
  id: "u-duty",
  display_name: "Daniel Mercer",
  email: "duty.officer@demo.nexira.invalid",
  roles: [{ code: "DUTY_OFFICER", mission_id: null, mission_code: null }],
};

export const ADMIN: Me = {
  id: "u-admin",
  display_name: "Nora Lind",
  email: "admin@demo.nexira.invalid",
  roles: [{ code: "ADMIN", mission_id: null, mission_code: null }],
};

type Routes = Record<string, { status?: number; body: unknown }>;

/** Stub fetch: path (without query) -> response. Returns the mock for assertions. */
export function mockApi(routes: Routes) {
  const fetchMock = vi.fn<typeof fetch>(async (input) => {
    const path = String(input).split("?")[0] ?? "";
    const route = routes[path];
    if (!route) return new Response("not found", { status: 404 });
    return new Response(JSON.stringify(route.body), {
      status: route.status ?? 200,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  setTokenProvider(() => Promise.resolve("test-token"));
  return fetchMock;
}

export type Reply = { status?: number; body: unknown };

/** Like mockApi, but keyed by "METHOD path", for paths that differ by method. */
export function mockServer(routes: Record<string, Reply>) {
  const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
    const path = String(input).split("?")[0] ?? "";
    const reply = routes[`${init?.method ?? "GET"} ${path}`];
    if (!reply) return new Response("not found", { status: 404 });
    return new Response(JSON.stringify(reply.body), {
      status: reply.status ?? 200,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  setTokenProvider(() => Promise.resolve("test-token"));
  return fetchMock;
}

export function renderApp(path: string, onLogout = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <App onLogout={onLogout} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
