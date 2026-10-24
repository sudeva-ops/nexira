import "@blueprintjs/core/lib/css/blueprint.css";
import "./styles.css";

import { Classes } from "@blueprintjs/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import { setTokenProvider } from "./api/client";
import { App } from "./app/App";
import { getToken, initAuth, logout } from "./auth/keycloak";

document.body.classList.add(Classes.DARK);

const root = document.getElementById("root");
if (!root) throw new Error("#root missing from index.html");

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: (count, error) => count < 2 && !("status" in error) } },
});

initAuth()
  .then(() => {
    setTokenProvider(getToken);
    createRoot(root).render(
      <StrictMode>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <App onLogout={() => void logout()} />
          </BrowserRouter>
        </QueryClientProvider>
      </StrictMode>,
    );
  })
  .catch(() => {
    root.textContent = "Sign-in is unavailable. Check that the identity provider is running.";
  });
