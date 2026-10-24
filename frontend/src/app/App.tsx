import { NonIdealState } from "@blueprintjs/core";
import { Route, Routes } from "react-router-dom";

import type { ReactElement } from "react";

import { AuditScreen } from "../screens/audit/AuditScreen";
import { IncidentsScreen } from "../screens/incidents/IncidentsScreen";
import { OperationsScreen } from "../screens/operations/OperationsScreen";
import { PeopleScreen } from "../screens/people/PeopleScreen";
import { AppShell } from "./AppShell";
import { SCREENS } from "./screens";

// Screens that exist so far; the rest show a placeholder naming their prompt.
const BUILT: Record<string, ReactElement> = {
  "/operations": <OperationsScreen />,
  "/incidents": <IncidentsScreen />,
  "/people": <PeopleScreen />,
  "/audit": <AuditScreen />,
};

interface Props {
  onLogout: () => void;
}

export function App({ onLogout }: Props) {
  return (
    <Routes>
      <Route element={<AppShell onLogout={onLogout} />}>
        {SCREENS.map((s) => (
          <Route
            key={s.path}
            path={s.path}
            element={
              BUILT[s.path] ?? (
                <NonIdealState
                  icon={s.icon}
                  title={s.title}
                  description={`Built in ${s.builtIn}.`}
                />
              )
            }
          />
        ))}
        <Route path="*" element={<NonIdealState icon="search" title="Page not found" />} />
      </Route>
    </Routes>
  );
}
