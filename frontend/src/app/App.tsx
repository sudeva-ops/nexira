import { NonIdealState } from "@blueprintjs/core";
import { Route, Routes } from "react-router-dom";

import type { ReactElement } from "react";

import { AgentsScreen } from "../screens/agents/AgentsScreen";
import { AirScreen } from "../screens/air/AirScreen";
import { AuditScreen } from "../screens/audit/AuditScreen";
import { CheckinScreen } from "../screens/checkin/CheckinScreen";
import { DocumentsScreen } from "../screens/documents/DocumentsScreen";
import { EvacuationScreen } from "../screens/evacuation/EvacuationScreen";
import { FleetScreen } from "../screens/fleet/FleetScreen";
import { HazardsScreen } from "../screens/hazards/HazardsScreen";
import { HealthScreen } from "../screens/health/HealthScreen";
import { IncidentsScreen } from "../screens/incidents/IncidentsScreen";
import { JourneysScreen } from "../screens/journeys/JourneysScreen";
import { NotifyScreen } from "../screens/notify/NotifyScreen";
import { OperationsScreen } from "../screens/operations/OperationsScreen";
import { PartnersScreen } from "../screens/partners/PartnersScreen";
import { PeopleScreen } from "../screens/people/PeopleScreen";
import { PlaybooksScreen } from "../screens/playbooks/PlaybooksScreen";
import { DecisionQueueScreen } from "../screens/queue/DecisionQueueScreen";
import { BriefingScreen } from "../screens/executive/BriefingScreen";
import { AarPrint } from "../screens/aar/AarPrint";
import { AarScreen } from "../screens/aar/AarScreen";
import { CopilotReportPrint } from "../screens/copilot/CopilotReportPrint";
import { CopilotScreen } from "../screens/copilot/CopilotScreen";
import { ExercisesScreen } from "../screens/exercises/ExercisesScreen";
import { ExecutiveScreen } from "../screens/executive/ExecutiveScreen";
import { PredictiveScreen } from "../screens/predictive/PredictiveScreen";
import { ReplayScreen } from "../screens/replay/ReplayScreen";
import { SupplyScreen } from "../screens/supply/SupplyScreen";
import { TwinScreen } from "../screens/twin/TwinScreen";
import { VipScreen } from "../screens/vip/VipScreen";
import { AppShell } from "./AppShell";
import { SCREENS } from "./screens";

// Screens that exist so far; the rest show a placeholder naming their prompt.
const BUILT: Record<string, ReactElement> = {
  "/": <DecisionQueueScreen />,
  "/agents": <AgentsScreen />,
  "/operations": <OperationsScreen />,
  "/incidents": <IncidentsScreen />,
  "/people": <PeopleScreen />,
  "/health": <HealthScreen />,
  "/hazards": <HazardsScreen />,
  "/journeys": <JourneysScreen />,
  "/air": <AirScreen />,
  "/playbooks": <PlaybooksScreen />,
  "/evacuation": <EvacuationScreen />,
  "/fleet": <FleetScreen />,
  "/vip": <VipScreen />,
  "/notifications": <NotifyScreen />,
  "/partners": <PartnersScreen />,
  "/twin": <TwinScreen />,
  "/checkin": <CheckinScreen />,
  "/copilot": <CopilotScreen />,
  "/documents": <DocumentsScreen />,
  "/supply": <SupplyScreen />,
  "/predictive": <PredictiveScreen />,
  "/exercises": <ExercisesScreen />,
  "/aar": <AarScreen />,
  "/executive": <ExecutiveScreen />,
  "/audit": <AuditScreen />,
};

interface Props {
  onLogout: () => void;
}

export function App({ onLogout }: Props) {
  return (
    <Routes>
      {/* EXE-03: the print-ready briefing stands alone, without the shell. */}
      <Route path="/executive/briefing" element={<BriefingScreen />} />
      {/* AAR-07: the print-ready review stands alone too. */}
      <Route path="/aar/:id/print" element={<AarPrint />} />
      <Route path="/copilot/report/:id/print" element={<CopilotReportPrint />} />
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
        <Route path="/incidents/replay" element={<ReplayScreen />} />
        <Route path="*" element={<NonIdealState icon="search" title="Page not found" />} />
      </Route>
    </Routes>
  );
}
