import { NonIdealState } from "@blueprintjs/core";
import { Route, Routes } from "react-router-dom";

import type { ReactElement } from "react";

import { AgentsScreen } from "../screens/agents/AgentsScreen";
import { AirScreen } from "../screens/air/AirScreen";
import { AuditScreen } from "../screens/audit/AuditScreen";
import { CheckinScreen } from "../screens/checkin/CheckinScreen";
import { DocumentsScreen } from "../screens/documents/DocumentsScreen";
import { IncidentsScreen } from "../screens/incidents/IncidentsScreen";
import { JourneysScreen } from "../screens/journeys/JourneysScreen";
import { NotifyScreen } from "../screens/notify/NotifyScreen";
import { OperationsScreen } from "../screens/operations/OperationsScreen";
import { PartnersScreen } from "../screens/partners/PartnersScreen";
import { PeopleScreen } from "../screens/people/PeopleScreen";
import { PlaybooksScreen } from "../screens/playbooks/PlaybooksScreen";
import { DecisionQueueScreen } from "../screens/queue/DecisionQueueScreen";
import { AppShell } from "./AppShell";
import { SCREENS } from "./screens";

// Screens that exist so far; the rest show a placeholder naming their prompt.
const BUILT: Record<string, ReactElement> = {
  "/": <DecisionQueueScreen />,
  "/agents": <AgentsScreen />,
  "/operations": <OperationsScreen />,
  "/incidents": <IncidentsScreen />,
  "/people": <PeopleScreen />,
  "/journeys": <JourneysScreen />,
  "/air": <AirScreen />,
  "/playbooks": <PlaybooksScreen />,
  "/notifications": <NotifyScreen />,
  "/partners": <PartnersScreen />,
  "/checkin": <CheckinScreen />,
  "/documents": <DocumentsScreen />,
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
