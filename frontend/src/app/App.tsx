import { NonIdealState } from "@blueprintjs/core";
import { Route, Routes } from "react-router-dom";

import { AppShell } from "./AppShell";
import { SCREENS } from "./screens";

export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        {SCREENS.map((s) => (
          <Route
            key={s.path}
            path={s.path}
            element={
              <NonIdealState icon={s.icon} title={s.title} description={`Built in ${s.builtIn}.`} />
            }
          />
        ))}
        <Route path="*" element={<NonIdealState icon="search" title="Page not found" />} />
      </Route>
    </Routes>
  );
}
