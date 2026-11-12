import { Icon, NonIdealState } from "@blueprintjs/core";
import { useState } from "react";
import { Link } from "react-router-dom";

import { useFlights } from "../../api/flights";
import { useOperationsSummary, useSignals } from "../../api/intel";
import {
  type Activity,
  type AgentsState,
  LEVEL_COLOUR,
  LEVELS,
  useAgentActivity,
  useAgents,
  useProposals,
} from "../../api/proposals";
import { formatTime, HOME_TZ } from "../../app/time";
import { CountUp } from "../../ui/motion";
import { Card, Kpi } from "../../ui/primitives";
import { SkeletonRows } from "../../ui/Skeleton";
import { buckets } from "../../ui/spark";
import { useNow } from "../../ui/useNow";
import { metrics, queueOrder } from "./format";
import { ProposalCard } from "./ProposalCard";
import { agentChecks, watchingRows } from "./watching";

const POLICY = [
  "Logging, notes, enrichment",
  "Internal actions with an undo window",
  "Staff alerts, playbooks, citizen advisories",
  "Evacuation, mission closure (two people)",
  "Unknown actions: advice only",
];

type Tab = "pending" | "decided" | "all";

const DAY_MS = 24 * 3_600_000;

/** GFX-06 (D-55): what the agents are watching, from existing APIs, and each agent's latest entry
 *  in the activity log. It sits under Decisions so the left column is never blank (plan G-8). */
function WatchingNow({ agents, activity, now }: { agents: AgentsState | undefined; activity: Activity[]; now: number }) {
  const summary = useOperationsSummary().data;
  const flights = useFlights().data;
  const signals = useSignals(500).data; // the list Global Operations loads, so the same cache
  const rows = watchingRows(summary, flights, signals, now);
  const checks = agentChecks(agents?.agents ?? [], activity, agents?.paused ?? false);
  return (
    <Card icon="eye-open" title="Watching now" sub="From live data · simulated (D-19)" className="nx-watching">
      <div className="nx-istat nx-watch" aria-label="Watching now">
        {rows.map((r) => (
          <div key={r.label}>
            <b>{r.value}</b>
            <span>{r.label}</span>
            {r.detail && (
              <small className="nx-dim" title={r.detail}>
                {r.detail}
              </small>
            )}
          </div>
        ))}
      </div>
      <div className="nx-bd nx-checks" aria-label="Latest from each agent">
        {checks.map((c) => (
          <div key={c.code} className="nx-row">
            <b className="nx-agent">{c.name}</b>
            <span className="nx-grow nx-dim" title={c.text}>
              {c.text}
            </span>
            {c.at && <span className="nx-mono nx-dim">{formatTime(new Date(c.at), HOME_TZ)}</span>}
          </div>
        ))}
      </div>
    </Card>
  );
}

/** Decision Queue, the home screen (DQ-01..08). */
export function DecisionQueueScreen() {
  const { data: proposals, isPending } = useProposals();
  const agents = useAgents().data;
  const activity = useAgentActivity().data ?? [];
  const [tab, setTab] = useState<Tab>("pending");
  const all = [...(proposals ?? [])].sort(queueOrder);
  const lists: Record<Tab, typeof all> = {
    pending: all.filter((p) => p.status === "PENDING"),
    decided: all.filter((p) => p.status !== "PENDING"),
    all,
  };
  const m = metrics(all);
  const now = useNow(true, 60_000);
  const list = lists[tab];

  return (
    <div className="nx-pad">
      {agents?.paused ? (
        <div className="nx-banner red" role="status">
          <Icon icon="warning-sign" />
          <div className="nx-grow">
            <b>All agents paused (kill switch).</b> No new proposals; playbooks can still be run by
            hand. Pending proposals can still be decided.
          </div>
          <Link to="/agents">Agent console →</Link>
        </div>
      ) : (
        <div className="nx-banner" role="status">
          <Icon icon="predictive-analysis" />
          <div className="nx-grow">
            <b>{agents?.agents.length ?? 4} agents are watching incidents, exposure and playbooks.</b>{" "}
            They prepare decisions; a named person approves anything that sends messages, starts a
            playbook or moves people.
          </div>
          <Link to="/agents">Agent console →</Link>
        </div>
      )}
      <div className="nx-g4">
        <Kpi
          icon="inbox"
          label="Awaiting decision"
          value={<span className={m.pending ? "nx-pending" : "nx-safe"}><CountUp value={m.pending} /></span>}
          detail={m.pending ? "Oldest deadline first" : "Queue clear"}
          trend={{
            values: buckets(all.map((p) => p.created_at), now, DAY_MS, 24),
            label: "Proposals raised per hour, last 24 hours",
          }}
        />
        <Kpi icon="trending-up" label="Raised proactively" value={m.proactive} detail="Before an incident" />
        <Kpi
          icon="time"
          label="Median time to decide"
          value={m.medianDecideS === null ? "—" : `${m.medianDecideS} s`}
          detail="Decisions by people"
        />
        <Kpi
          icon="tick"
          label="Accepted by people"
          value={m.acceptedPct === null ? "—" : `${m.acceptedPct}%`}
          detail={`${m.decided} decisions`}
        />
      </div>
      <div className="nx-queue">
        <div>
          <div className="nx-tabs nx-mb" role="tablist">
            {(
              [
                ["pending", `Pending (${lists.pending.length})`],
                ["decided", `Decided (${lists.decided.length})`],
                ["all", "All"],
              ] as const
            ).map(([key, label]) => (
              <button
                key={key}
                type="button"
                role="tab"
                aria-selected={tab === key}
                className={tab === key ? "on" : undefined}
                onClick={() => setTab(key)}
              >
                {label}
              </button>
            ))}
          </div>
          {isPending ? (
            <SkeletonRows />
          ) : list.length ? (
            list.map((p) => <ProposalCard key={p.id} p={p} />)
          ) : (
            <Card title="Decisions">
              <NonIdealState
                icon="inbox"
                title={tab === "pending" ? "No decisions waiting" : "Nothing here yet"}
                description={agents?.paused ? "Agents are paused." : "Agents raise proposals as conditions change."}
              />
            </Card>
          )}
          <WatchingNow agents={agents} activity={activity} now={now} />
        </div>
        <div className="nx-col">
          <Card
            icon="predictive-analysis"
            title="Agent activity"
            actions={<span className="nx-chip">Live</span>}
            className="nx-fill"
          >
            <div className="nx-bd nx-log nx-activity" aria-label="Agent activity">
              {activity.length ? (
                activity.map((a, i) => (
                  <div key={i}>
                    <span>{formatTime(new Date(a.occurred_at), HOME_TZ)}</span>
                    <b className={a.actor === "Human" ? "nx-safe" : "nx-agent"}>{a.actor}</b> · {a.text}
                  </div>
                ))
              ) : (
                <div className="nx-dim">Agents are watching…</div>
              )}
            </div>
          </Card>
          <Card icon="shield" title="Decision policy">
            <div className="nx-bd nx-policy">
              {LEVELS.map((label, i) => (
                <div key={label} className="nx-row">
                  <span className="nx-chip" style={{ color: LEVEL_COLOUR[i], minWidth: 104 }}>
                    {label}
                  </span>
                  <span className="nx-dim">{POLICY[i]}</span>
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
