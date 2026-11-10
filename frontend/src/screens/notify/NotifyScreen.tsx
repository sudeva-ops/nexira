import { HTMLSelect, NonIdealState } from "@blueprintjs/core";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import {
  type CampaignFilters,
  type NtfCampaign,
  useNtfCampaign,
  useNtfCampaigns,
} from "../../api/notifications";
import { useMissions } from "../../api/people";
import { formatStamp } from "../../app/time";
import { FlashRow } from "../../ui/motion";
import { Card, ExerciseTag, Kpi } from "../../ui/primitives";
import { SkeletonRows } from "../../ui/Skeleton";
import { CampaignDetail } from "./CampaignDetail";
import { Composer } from "./Composer";

const DAY_MS = 86_400_000;
const STATUS: Record<string, [string, string]> = {
  DRAFT: ["Draft", "nx-dim"],
  PENDING_APPROVAL: ["Awaiting approval", "nx-pending"],
  SENDING: ["Sending", "nx-info"],
  SENT: ["Sent", "nx-safe"],
  CANCELLED: ["Cancelled", "nx-dim"],
};

function audienceText(c: NtfCampaign, missionCode: (id: string) => string): string {
  const types = c.audience_filter.person_types?.map((t) => t.toLowerCase().replace("_", " ")).join(", ");
  if (c.audience_filter.trip_id) return "A trip's travellers (Travel & Air)";
  if (c.audience_filter.exposed) return `Exposed to the incident${types ? ` · ${types}` : ""}`;
  if (c.audience_filter.missions) {
    return `${c.audience_filter.missions.map(missionCode).join(", ")}${types ? ` · ${types}` : ""}`;
  }
  return c.created_by_type === "PLAYBOOK" ? "Playbook audience" : "—";
}

/** Mass Notification (MN-01..10; D-30, D-31): compose, approve, follow delivery. */
export function NotifyScreen() {
  const [params, setParams] = useSearchParams();
  const [filters, setFilters] = useState<CampaignFilters>({});
  const [editing, setEditing] = useState<NtfCampaign | null>(null);
  const [now] = useState(() => Date.now()); // the 24 h figures are as of opening the screen
  const campaigns = useNtfCampaigns(filters);
  const missions = useMissions().data ?? [];
  const selectedId = params.get("campaign") ?? undefined;
  const selected = useNtfCampaign(selectedId).data;
  const missionCode = (id: string) => missions.find((m) => m.id === id)?.code ?? "?";
  const select = (id: string) => setParams({ campaign: id });

  const list = campaigns.data ?? [];
  const recent = list.filter((c) => c.sent_at && now - Date.parse(c.sent_at) < DAY_MS);
  const totals = recent.reduce(
    (t, c) => {
      for (const [status, n] of Object.entries(c.deliveries)) t[status] = (t[status] ?? 0) + n;
      return t;
    },
    {} as Record<string, number>,
  );
  const delivered = (totals.DELIVERED ?? 0) + (totals.READ ?? 0);
  const all = Object.values(totals).reduce((a, b) => a + b, 0);

  return (
    <div className="nx-pad">
      <div className="nx-g4">
        <Kpi
          icon="time"
          label="Awaiting approval"
          value={list.filter((c) => c.status === "PENDING_APPROVAL").length}
          detail="Citizen messages need a second person (D-31)"
          alert={list.some((c) => c.status === "PENDING_APPROVAL")}
        />
        <Kpi icon="send-message" label="Campaigns sent · 24h" value={recent.length} detail={`${all} deliveries`} />
        <Kpi
          icon="tick"
          label="Delivered or read · 24h"
          value={all ? `${Math.round((delivered / all) * 100)}%` : "—"}
          detail="Simulated channels (D-19)"
        />
        <Kpi
          icon="warning-sign"
          label="Failed · 24h"
          value={totals.FAILED ?? 0}
          detail="No fallback in the pilot (MN-11 deferred)"
        />
      </div>

      <div className="nx-ntf-grid">
        <div className="nx-col">
          <Card
            icon="send-message"
            title="Campaigns"
            sub={`${list.length} shown · playbooks, agents and people`}
            actions={
              <div className="nx-row">
                <HTMLSelect
                  minimal
                  aria-label="Filter by kind"
                  value={filters.kind ?? ""}
                  onChange={(e) => setFilters({ ...filters, kind: e.currentTarget.value || undefined })}
                  options={[
                    { value: "", label: "All kinds" },
                    { value: "ALERT", label: "Alerts" },
                    { value: "ADVISORY", label: "Advisories" },
                    { value: "CHECKIN", label: "Check-ins" },
                  ]}
                />
                <HTMLSelect
                  minimal
                  aria-label="Filter by status"
                  value={filters.status ?? ""}
                  onChange={(e) => setFilters({ ...filters, status: e.currentTarget.value || undefined })}
                  options={[
                    { value: "", label: "All statuses" },
                    ...Object.entries(STATUS).map(([value, [label]]) => ({ value, label })),
                  ]}
                />
                <HTMLSelect
                  minimal
                  aria-label="Filter by mission"
                  value={filters.mission_id ?? ""}
                  onChange={(e) =>
                    setFilters({ ...filters, mission_id: e.currentTarget.value || undefined })
                  }
                  options={[
                    { value: "", label: "All missions" },
                    ...missions.map((m) => ({ value: m.id, label: m.code })),
                  ]}
                />
              </div>
            }
          >
            {campaigns.isLoading ? (
              <SkeletonRows />
            ) : list.length === 0 ? (
              <NonIdealState icon="send-message" title="No campaigns" description="Nothing matches these filters." />
            ) : (
              <div className="nx-ntf-scroll">
              <table className="nx-table-plain" aria-label="Campaigns">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Message</th>
                    <th>Audience</th>
                    <th>Status</th>
                    <th>Recipients</th>
                    <th>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {list.map((c) => (
                    <FlashRow
                      key={c.id}
                      watch={`${c.status} ${c.recipients}`}
                      tone={c.status === "SENT" ? "success" : "info"}
                      className={c.id === selectedId ? "on" : undefined}
                      onClick={() => select(c.id)}
                    >
                      <td className="nx-mono nx-dim nx-nowrap">
                        {c.reference} <ExerciseTag on={c.exercise} />
                      </td>
                      <td>
                        <button type="button" className="nx-linkbtn" onClick={() => select(c.id)}>
                          {c.message}
                        </button>
                      </td>
                      <td>{audienceText(c, missionCode)}</td>
                      <td className={STATUS[c.status]?.[1]}>{STATUS[c.status]?.[0] ?? c.status}</td>
                      <td className="nx-mono">{c.recipients || "—"}</td>
                      <td className="nx-dim nx-nowrap">{formatStamp(c.created_at)}</td>
                    </FlashRow>
                  ))}
                </tbody>
              </table>
              </div>
            )}
          </Card>
          {selected && <CampaignDetail campaign={selected} onEdit={setEditing} />}
        </div>
        <Composer
          key={editing?.id ?? "new"}
          editing={editing}
          onDone={(c) => {
            setEditing(null);
            select(c.id);
          }}
        />
      </div>
    </div>
  );
}
