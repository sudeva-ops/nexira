import { oidcUrl } from "./keycloak";

describe("oidcUrl", () => {
  it("keeps an absolute URL and resolves a path on the app's own origin", () => {
    expect(oidcUrl("http://localhost:8080", "http://localhost:3000")).toBe("http://localhost:8080");
    expect(oidcUrl(undefined, "http://localhost:3000")).toBe("http://localhost:8080");
    expect(oidcUrl("/auth", "https://demo-3000.app.github.dev")).toBe("https://demo-3000.app.github.dev/auth");
    expect(oidcUrl("/auth/", "http://localhost:3000")).toBe("http://localhost:3000/auth");
  });
});
