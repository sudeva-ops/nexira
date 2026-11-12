import { Button, HTMLSelect, Icon } from "@blueprintjs/core";
import { useState } from "react";

import { ApiError } from "../../api/client";
import { useMe } from "../../api/me";
import {
  ACTION_LABEL,
  LEVEL_COLOUR,
  LEVELS,
  useAgents,
  useKillSwitch,
  useAgentActivity,
  useProposals,
  useSetAutonomy,
} from "../../api/proposals";
import { roleLabel } from "../../ui/format";
import { CountUp } from "../../ui/motion";
import { Card, Kpi } from "../../ui/primitives";
import { buckets } from "../../ui/spark";
import { Sparkline } from "../../ui/Sparkline";
import { useNow } from "../../ui/useNow";
import { useAssessing } from "./useAssessing";
import { TileRow } from "../../ui/TileRow";
import { SkeletonRows } from "../../ui/Skeleton";
import { ContextLine } from "../../ui/ContextLine";

const HOUR_MS = 3_600_000;

const WATCHES: Record<string, string> = {
  INCIDENT_CREATED: "New incidents",
  EXPOSURE_COMPUTED: "Exposure of people and sites",
  PLAYBOOK_STEP: "Playbook steps",
  FLIGHT_UPDATED: "Tracked flights",
};

const GUARDRAILS = [
  "No external message, playbook or movement of people without a named person's approval",
  "Evacuation and mission closure need two different approvers",
  "Every proposal cites its evidence, sources and confidence",
  "Agents act only through the services people use; every step is in the audit log",
  "No external AI calls; models run on the platform's own infrastructure",
  "Travel & Air books nothing and never proposes anything about restricted (VIP) trips",
];

function KillSwitch({ paused }: { paused: boolean }) {
  const [confirming, setConfirming] = useState(false);
  const toggle = useKillSwitch();
  if (!confirming) {
    return (
      <Button
        size="small"
        intent={paused ? "primary" : "danger"}
        text={paused ? "Resume all agents" : "Kill switch · pause all"}
        onClick={() => setConfirming(true)}
      />
    );
  }
  return (
    <div className="nx-row" role="group" aria-label="Confirm kill switch">
      <span>{paused ? "Resume all agents?" : "Pause all agents now?"}</span>
      <Button
        size="small"
        intent={paused ? "primary" : "danger"}
        text={paused ? "Yes, resume" : "Yes, pause all"}
        loading={toggle.isPending}
        onClick={() => toggle.mutate(!paused, { onSuccess: () => setConfirming(false) })}
      />
      <Button size="small" text="Cancel" onClick={() => setConfirming(false)} />
      {toggle.isError && (
        <span className="nx-error">
          {toggle.error instanceof ApiError ? toggle.error.message : "Not changed"}
        </span>
      )}
    </div>
  );
}

/** AI Agents (AGT-07, AGT-08): roster, autonomy (ADMIN), kill switch (ADMIN). */
export function AgentsScreen() {
  const { data } = useAgents();
  const proposals = useProposals().data ?? [];
  const me = useMe().data;
  const setAutonomy = useSetAutonomy();
  // Unscoped ADMIN only (the backend requires it too).
  const admin = me?.roles.some((r) => r.code === "ADMIN" && r.mission_id === null) ?? false;
  const assessing = useAssessing(data?.agents ?? []);
  const activity = useAgentActivity().data ?? [];
  const now = useNow(true, 30_000);
  if (!data) return <SkeletonRows rows={8} />;

  const decided = proposals.filter((p) => ["APPROVED", "EDITED_APPROVED", "REJECTED"].includes(p.status));
  const overridden = decided.filter((p) => p.status !== "APPROVED").length;
  // Executed without the approvals its level requires: computed, expected to be 0.
  const outside = proposals.filter(
    (p) =>
      ["APPROVED", "EDITED_APPROVED"].includes(p.status) &&
      p.approvals.filter((a) => a.decision === "APPROVE").length < (p.effective_level === 3 ? 2 : 1),
  ).length;

  return (
    <div className="nx-pad">
      {data.paused ? (
        <div className="nx-banner red" role="status">
          <Icon icon="pause" />
          <div className="nx-grow">
            <b>Agents paused.</b> Agents act only through the platform's services, with the
            approvals their level requires; every output is logged.
          </div>
          {admin && <KillSwitch paused />}
        </div>
      ) : (
        <ContextLine actions={admin && <KillSwitch paused={false} />}>
          Agents active. They act only through the platform&apos;s services, with the approvals their
          level requires; every output is logged.
        </ContextLine>
      )}
      <TileRow>
        <Kpi
          icon="predictive-analysis"
          label="Agents"
          value={data.agents.length}
          detail={data.paused ? "Paused" : `${data.agents.filter((a) => a.is_enabled).length} enabled`}
        />
        <Kpi icon="inbox" label="Proposals" value={proposals.length} detail={`${proposals.filter((p) => p.status === "PENDING").length} pending`} />
        <Kpi
          icon="people"
          label="Human override rate"
          value={decided.length ? `${Math.round((overridden / decided.length) * 100)}%` : "—"}
          detail="Edited or rejected"
        />
        <Kpi
          icon="shield"
          label="Executed without approval"
          value={<span className={outside ? "nx-help" : "nx-safe"}><CountUp value={outside} /></span>}
          detail="Checked against each proposal's approvals"
        />
      </TileRow>
      <Card
        icon="predictive-analysis"
        title="Agent roster"
        sub="Autonomy per agent; policy floors still apply (evacuation always needs two approvers)"
      >
        <table className="nx-table-plain" aria-label="Agent roster">
          <thead>
            <tr>
              <th>Agent</th>
              <th>Watches</th>
              <th>Proposes · who decides</th>
              <th>Autonomy level</th>
              <th>Proposals</th>
              <th>Accepted</th>
              <th>Pending</th>
              <th>Last hour</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {data.agents.map((a) => (
              <tr key={a.code}>
                <td>
                  <b>{a.name}</b>
                  {a.description && <div className="nx-dim">{a.description}</div>}
                </td>
                <td>{a.watches.map((w) => WATCHES[w] ?? w).join(", ")}</td>
                <td>
                  {a.actions.map((x) => (
                    <div key={x.action_type} className="nx-agent-action">
                      {ACTION_LABEL[x.action_type] ?? x.action_type}{" "}
                      <span style={{ color: LEVEL_COLOUR[x.level] }}>· {LEVELS[x.level]}</span>
                      {x.approver_roles.length > 0 && (
                        <span className="nx-dim"> · {x.approver_roles.map(roleLabel).join(", then ")}</span>
                      )}
                    </div>
                  ))}
                </td>
                <td>
                  {admin ? (
                    <HTMLSelect
                      aria-label={`Autonomy for ${a.name}`}
                      value={a.autonomy_level}
                      onChange={(e) =>
                        setAutonomy.mutate({ code: a.code, autonomy_level: Number(e.currentTarget.value) })
                      }
                      options={LEVELS.map((label, i) => ({ value: i, label }))}
                    />
                  ) : (
                    <span style={{ color: LEVEL_COLOUR[a.autonomy_level] }}>{LEVELS[a.autonomy_level]}</span>
                  )}
                </td>
                <td className="nx-mono">{a.proposals_total}</td>
                <td className="nx-mono">{a.accepted_pct === null ? "—" : `${a.accepted_pct}%`}</td>
                <td className="nx-mono">{a.proposals_pending}</td>
                <td>
                  <Sparkline
                    values={buckets(
                      activity.filter((x) => x.actor === a.name).map((x) => x.occurred_at),
                      now,
                      HOUR_MS,
                      12,
                    )}
                    label={`${a.name} activity, last hour`}
                  />
                </td>
                <td>
                  {data.paused ? (
                    <span className="nx-sev crit">PAUSED</span>
                  ) : a.is_enabled && assessing.has(a.code) ? (
                    <span className="nx-sev ok nx-assessing">
                      ASSESSING
                      <i />
                      <i />
                      <i />
                    </span>
                  ) : a.is_enabled ? (
                    <span className="nx-sev ok">ACTIVE</span>
                  ) : (
                    <span className="nx-sev nt">DISABLED</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      <Card icon="shield" title="Guardrails">
        <div className="nx-bd nx-guardrails">
          {GUARDRAILS.map((g) => (
            <div key={g} className="nx-row">
              <Icon icon="tick" size={12} className="nx-safe" />
              {g}
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

