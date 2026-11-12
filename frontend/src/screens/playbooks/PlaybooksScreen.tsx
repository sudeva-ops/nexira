import { Button, HTMLSelect, Icon, NonIdealState } from "@blueprintjs/core";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { useEntityAudit } from "../../api/audit";
import { ApiError } from "../../api/client";
import { useIncidents } from "../../api/intel";
import { useMe } from "../../api/me";
import { canStartPlaybook } from "../../api/permissions";
import {
  type Playbook,
  type PlaybookRun,
  type RunStep,
  useApproveStep,
  usePlaybooks,
  useRun,
  useRunPermissions,
  useRuns,
  useStartRun,
} from "../../api/playbooks";
import { formatStamp } from "../../app/time";
import { Card, Kpi } from "../../ui/primitives";
import { playbookFigures } from "../../ui/figures";
import { TileRow } from "../../ui/TileRow";
import { useNow } from "../../ui/useNow";
import { plural, roleLabel } from "../../ui/format";
import { ACTION_ICON, STEP_CLASS, stepDetail } from "./steps";
import { Empty } from "../../ui/Empty";
import { SkeletonRows } from "../../ui/Skeleton";

const LIVE = ["RUNNING", "AWAITING_APPROVAL"];

function errorText(error: unknown): string {
  return error instanceof ApiError ? error.message : "Something went wrong";
}

function StartRun({ playbook, again }: { playbook: Playbook; again: boolean }) {
  const me = useMe().data;
  const incidents = (useIncidents("ACTIVE").data ?? []).filter((i) =>
    canStartPlaybook(me, i.mission_id),
  );
  const [incidentId, setIncidentId] = useState("");
  const start = useStartRun();
  const [, setParams] = useSearchParams();
  if (incidents.length === 0) return null;
  const chosen = incidentId || incidents[0]?.id || "";
  return (
    <div className="nx-row">
      <HTMLSelect
        aria-label="Incident"
        value={chosen}
        onChange={(e) => setIncidentId(e.currentTarget.value)}
        options={incidents.map((i) => ({ value: i.id, label: `${i.reference} · ${i.place_label ?? ""}` }))}
      />
      <Button
        intent="danger"
        size="small"
        icon="play"
        text={again ? "Run again" : "Run playbook"}
        loading={start.isPending}
        onClick={() =>
          start.mutate(
            { playbook_code: playbook.code, incident_id: chosen },
            { onSuccess: (run) => setParams({ code: playbook.code, run: run.id }) },
          )
        }
      />
      {start.isError && <span className="nx-error">{errorText(start.error)}</span>}
    </div>
  );
}

function Step({ step, run, approvable }: { step: RunStep; run: PlaybookRun; approvable: boolean }) {
  const approve = useApproveStep(run.id);
  return (
    <div className={`nx-step ${STEP_CLASS[step.status] ?? "pend"}`} data-testid={`step-${step.seq}`}>
      <div className="ic">
        <Icon icon={step.status === "DONE" ? "tick" : (ACTION_ICON[step.action_type] ?? "dot")} size={12} />
      </div>
      <div className="nx-grow">
        <div className="tt">
          {step.seq}. {step.name}
        </div>
        <div className="ds">{stepDetail(step)}</div>
        {step.status === "RUNNING" && <div className="nx-running">Executing…</div>}
        {approvable && step.requires_approval_role && (
          <div className="nx-row nx-step-actions">
            <Button
              intent="primary"
              size="small"
              icon="tick"
              text={`Approve as ${roleLabel(step.requires_approval_role)}`}
              loading={approve.isPending}
              onClick={() => approve.mutate(step.id)}
            />
            {approve.isError && <span className="nx-error">{errorText(approve.error)}</span>}
          </div>
        )}
      </div>
      <div className="meta">
        {step.status === "DONE" && step.completed_at ? (
          formatStamp(step.completed_at).split(" ").slice(2).join(" ")
        ) : step.status === "AWAITING_APPROVAL" ? (
          <span className="nx-await">Awaiting approval</span>
        ) : null}
      </div>
    </div>
  );
}

function RunView({ playbook, run }: { playbook: Playbook; run: PlaybookRun | undefined }) {
  const permissions = useRunPermissions(run?.id).data;
  const steps: RunStep[] =
    run?.steps ??
    playbook.steps.map((s) => ({
      ...s,
      status: "PENDING",
      started_at: null,
      completed_at: null,
      approved_by: null,
      approved_by_name: null,
      result: {},
    }));
  const done = steps.filter((s) => s.status === "DONE").length;
  const live = run && LIVE.includes(run.status);
  return (
    <Card
      title={`${playbook.code} · ${playbook.name}`}
      sub={
        run
          ? `${run.incident_reference ?? "No incident"} · started by ${run.started_by_name ?? run.started_by_type.toLowerCase()} · ${run.status.replace("_", " ").toLowerCase()}`
          : "Ready · not triggered"
      }
      actions={
        run ? <span className="nx-chip nx-mono">{done}/{steps.length} complete</span> : null
      }
      className="nx-scroll"
    >
      <div className="nx-bd nx-run">
        {!live && <StartRun playbook={playbook} again={!!run} />}
        {run && (
          <div className="nx-bar nx-progress" aria-label="Progress">
            <i style={{ width: `${(done / steps.length) * 100}%`, background: "#32A467" }} />
          </div>
        )}
        <div className="nx-steps" aria-label="Steps">
          {steps.map((s) =>
            run ? (
              <Step
                key={s.id}
                step={s}
                run={run}
                approvable={permissions?.approve_step.includes(s.id) ?? false}
              />
            ) : (
              <div key={s.id} className="nx-step pend" data-testid={`step-${s.seq}`}>
                <div className="ic">
                  <Icon icon={ACTION_ICON[s.action_type] ?? "dot"} size={12} />
                </div>
                <div className="nx-grow">
                  <div className="tt">
                    {s.seq}. {s.name}
                  </div>
                  <div className="ds">{stepDetail(s)}</div>
                </div>
              </div>
            ),
          )}
        </div>
      </div>
    </Card>
  );
}

function AuditTrail({ runId }: { runId: string | undefined }) {
  const { data } = useEntityAudit("playbook_run", runId);
  return (
    <Card
      icon="history"
      title="Audit trail"
      className="nx-side"
      chip={{ text: "Hash-chained", tone: "ok" }}
    >
      <div className="nx-bd nx-log" aria-label="Audit trail">
        {data?.length ? (
          data.map((e) => (
            <div key={e.chain_seq}>
              <span>{formatStamp(e.occurred_at).split(" ").slice(2, 3).join("")}</span>
              {e.action}
              {typeof e.details.seq === "number" && ` · step ${e.details.seq}`}
              {e.actor_type === "USER" && " · by a user"}
            </div>
          ))
        ) : (
          <Empty>No events yet.</Empty>
        )}
      </div>
    </Card>
  );
}

/** Response Playbooks (PB-01..04). */
export function PlaybooksScreen() {
  const [params, setParams] = useSearchParams();
  const playbooks = usePlaybooks();
  const runs = useRuns().data ?? [];
  const code = params.get("code") ?? playbooks.data?.[0]?.code;
  const playbook = playbooks.data?.find((p) => p.code === code);
  const forPlaybook = runs.filter((r) => r.playbook_code === code);
  const runId = params.get("run") ?? forPlaybook[0]?.id;
  const runQuery = useRun(runId);
  const run = runQuery.data;
  const now = useNow(true, 60_000);
  const f = playbookFigures(runs, now);

  if (playbooks.isPending) return <SkeletonRows rows={6} />;
  if (!playbook) return <NonIdealState icon="flash" title="No playbooks" />;
  return (
    <div className="nx-pad">
      {/* DC-01 (plan G-2): from the library and the runs the screen loads */}
      <TileRow label="Playbook figures">
        <Kpi icon="flash" label="Playbooks" value={playbooks.data?.length ?? 0} detail="In the library" />
        <Kpi
          icon="play"
          label="Runs active"
          value={f.active}
          detail={f.armed ? `${f.armed} armed to start by itself` : "Running or waiting"}
        />
        <Kpi
          icon="hand"
          label="Waiting at a gate"
          value={<span className={f.atGate ? "nx-pending" : undefined}>{f.atGate}</span>}
          detail="A step needs a named approver"
        />
        <Kpi
          icon="history"
          label="Runs · 30 days"
          value={f.runs30}
          detail={`${f.byAgent} started from an agent's proposal`}
        />
      </TileRow>
      <div className="nx-pbgrid">
      <Card
        icon="flash"
        title="Playbook library"
        chip={{ text: plural(playbooks.data?.length ?? 0, "playbook") }}
        className="nx-scroll"
      >
        {playbooks.data?.map((p) => {
          const running = runs.some((r) => r.playbook_code === p.code && LIVE.includes(r.status));
          return (
            <button
              type="button"
              key={p.id}
              className={`nx-pbitem${p.code === code ? " on" : ""}`}
              onClick={() => setParams({ code: p.code })}
            >
              <div className="nx-row">
                <span className="c">
                  {p.code} · {p.category.replace("_", " ")}
                </span>
                <span className="nx-grow" />
                {running && <span className="nx-sev crit">RUNNING</span>}
              </div>
              <div className="t">{p.name}</div>
              <div className="nx-dim">{p.steps.length} steps</div>
            </button>
          );
        })}
        {forPlaybook.length > 1 && (
          <div className="nx-bd">
            <div className="nx-lbl">Runs of {code}</div>
            <HTMLSelect
              aria-label="Run"
              fill
              value={runId}
              onChange={(e) => setParams({ code: code ?? "", run: e.currentTarget.value })}
              options={forPlaybook.map((r) => ({
                value: r.id,
                label: `${formatStamp(r.started_at)} · ${r.incident_reference ?? ""} · ${r.status}`,
              }))}
            />
          </div>
        )}
      </Card>
      {runId && runQuery.isPending ? (
        <Card title={`${playbook.code} · ${playbook.name}`}>
          <SkeletonRows />
        </Card>
      ) : (
        <RunView playbook={playbook} run={run} />
      )}
      <AuditTrail runId={run?.id} />
    </div>
    </div>
  );
}
