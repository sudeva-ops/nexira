import {
  Button,
  HTMLSelect,
  Icon,
  InputGroup,
  NonIdealState,
} from "@blueprintjs/core";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { ApiError } from "../../api/client";
import { useMissions } from "../../api/people";
import {
  type Banner,
  bannerTitle,
  defaultSupplyMission,
  type Mitigation,
  type Route,
  SHOWN_LABEL,
  SHOWN_SEV,
  type ShownRouteStatus,
  type ShownStatus,
  type Supplier,
  type SupplierDetail,
  useActivateMitigation,
  useStandDown,
  useSupplier,
  useSuppliers,
  useSupplyPermissions,
  useSupplySummary,
} from "../../api/supply";
import { formatStamp } from "../../app/time";
import { FlashRow } from "../../ui/motion";
import { Card, Kpi } from "../../ui/primitives";
import { SkeletonRows } from "../../ui/Skeleton";

function errorText(error: unknown): string {
  return error instanceof ApiError ? error.message : "Not done";
}

function Sev({ status }: { status: ShownStatus | ShownRouteStatus }) {
  return (
    <span className={`nx-sev ${SHOWN_SEV[status]}`}>{SHOWN_LABEL[status]}</span>
  );
}

/** SUP-03: one banner per ACTIVE incident with impacted third parties. */
function ImpactBanner({ banners }: { banners: Banner[] }) {
  if (!banners.length) return null;
  return (
    <>
      {banners.map((b) => (
        <div
          key={b.incident_id}
          className="nx-banner nx-mb red"
          role="alert"
          data-testid="supply-banner"
        >
          <Icon icon="box" />
          <div className="nx-grow">
            <b>{bannerTitle(b)}</b>{" "}
            {b.suppliers
              .map(
                (s) =>
                  `${s.name}: ${SHOWN_LABEL[s.shown].toLowerCase()}${s.detail ? ` (${s.detail})` : ""}`,
              )
              .join(" · ")}
          </div>
        </div>
      ))}
    </>
  );
}

function SuppliersCard({
  suppliers,
  loading,
  selected,
  onSelect,
  total,
}: {
  suppliers: Supplier[];
  loading: boolean;
  selected: string | undefined;
  onSelect: (id: string) => void;
  total: number | undefined;
}) {
  return (
    <Card
      icon="box"
      title="Suppliers & third parties"
      sub={total ? `${suppliers.length} of ${total} shown` : undefined}
    >
      {loading ? (
        <SkeletonRows rows={6} />
      ) : !suppliers.length ? (
        <NonIdealState
          icon="box"
          title="No suppliers"
          description="No third parties for this mission."
        />
      ) : (
        <table
          className="nx-table-plain nx-sup-table"
          aria-label="Suppliers and third parties"
        >
          <thead>
            <tr>
              <th>ID</th>
              <th>Supplier</th>
              <th>Service</th>
              <th>Mission</th>
              <th>Tier</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {suppliers.map((s) => (
              <FlashRow
                key={s.id}
                data-supplier={s.code}
                aria-selected={s.id === selected}
                className={s.id === selected ? "nx-sup-selected" : undefined}
                watch={s.shown}
                tone={s.impacted ? "danger" : "info"}
                onClick={() => onSelect(s.id)}
              >
                <td className="nx-mono nx-dim">{s.code}</td>
                <td>
                  <b>{s.name}</b>
                </td>
                <td>{s.service}</td>
                <td>{s.city ?? "Global"}</td>
                <td className="nx-mono">T{s.tier}</td>
                <td>
                  <Sev status={s.shown} />
                </td>
              </FlashRow>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}

function Tick({
  done,
  label,
  detail,
}: {
  done: boolean;
  label: string;
  detail?: string;
}) {
  return (
    <li className="nx-row" data-done={done}>
      <Icon
        icon={done ? "tick-circle" : "circle"}
        intent={done ? "success" : undefined}
      />
      <span className="nx-grow">{label}</span>
      {detail && <span className="nx-dim nx-sup-detail">{detail}</span>}
    </li>
  );
}

function MitigationText({ m }: { m: Mitigation }) {
  const parts = [
    m.backup && `${m.backup.name} on standby`,
    m.route_label && `${m.route_label} in use`,
  ].filter(Boolean);
  return (
    <div className="nx-sup-mitigation" data-testid="supply-mitigation">
      <div>
        <Icon icon="shield" intent="success" size={12} />{" "}
        <b>Mitigation active</b> since {formatStamp(m.activated_at)} ·{" "}
        {m.activated_by_name ?? "Activated"}
        {m.incident_reference && ` · ${m.incident_reference}`}
      </div>
      {parts.length > 0 && <div className="nx-dim">{parts.join(" · ")}</div>}
      {m.note && <div className="nx-dim">Note: {m.note}</div>}
    </div>
  );
}

/** The selected supplier: status, dependencies, fuel stock and the mitigation (SUP-01, SUP-04). */
function SupplierCard({ detail }: { detail: SupplierDetail }) {
  const allowed = useSupplyPermissions(detail.id).data;
  const activate = useActivateMitigation();
  const standDown = useStandDown();
  const [note, setNote] = useState("");
  const m = detail.mitigation;
  return (
    <Card
      icon="document"
      title={detail.name}
      sub={`${detail.code} · ${detail.service}`}
    >
      <div className="nx-bd nx-sup-card">
        <div className="nx-row nx-sup-chips">
          <Sev status={detail.shown} />
          <span className="nx-chip">Tier {detail.tier}</span>
          <span className="nx-chip">{detail.city ?? "Global"}</span>
        </div>
        <div>
          {detail.detail ??
            `No active disruption.${detail.performance_score !== null ? ` Last performance review ${detail.performance_score}/100.` : ""}`}
        </div>
        {detail.fuel_stock_hours !== null && (
          <div className="nx-dim">
            {detail.fuel_stock_hours} h on-site stock · generator fuel from
            Fleet & Assets
          </div>
        )}
        <div className="nx-lbl">Dependencies</div>
        <ul className="nx-sup-list" aria-label="Dependencies">
          <Tick
            done={!!detail.backup}
            label="Backup supplier identified"
            detail={detail.backup?.name}
          />
          <Tick done={detail.in_bcp} label="Included in mission BCP" />
          <Tick
            done={detail.vetting_current}
            label="Security vetting current"
            detail={`until ${detail.vetting_valid_until}`}
          />
        </ul>
        {m && <MitigationText m={m} />}
        {allowed?.activate_mitigation && (
          <div className="nx-row nx-sup-act">
            <InputGroup
              small
              aria-label="Note"
              placeholder="Note (optional, audited, seen by every role: no names)"
              value={note}
              maxLength={500}
              onChange={(e) => setNote(e.currentTarget.value)}
            />
            <Button
              size="small"
              intent="primary"
              icon="flash"
              text="Activate mitigation"
              loading={activate.isPending}
              onClick={() =>
                activate.mutate(
                  { id: detail.id, note: note.trim() || null },
                  { onSuccess: () => setNote("") },
                )
              }
            />
          </div>
        )}
        {m && allowed?.stand_down_mitigation && (
          <Button
            size="small"
            className="nx-sup-standdown"
            text="Stand down"
            loading={standDown.isPending}
            onClick={() => standDown.mutate(m.id)}
          />
        )}
        {(allowed?.activate_mitigation || m) && (
          <div className="nx-dim nx-sup-note">
            NEXIRA records the decision; nothing is sent to the supplier.
          </div>
        )}
        {activate.isError && (
          <div className="nx-error">{errorText(activate.error)}</div>
        )}
        {standDown.isError && (
          <div className="nx-error">{errorText(standDown.error)}</div>
        )}
      </div>
    </Card>
  );
}

function RoutesCard({ detail }: { detail: SupplierDetail }) {
  return (
    <Card icon="route" title={`Logistics routes · ${detail.city ?? "Global"}`}>
      {!detail.routes.length ? (
        <div className="nx-bd nx-dim">No logistics routes monitored.</div>
      ) : (
        <table
          className="nx-table-plain nx-sup-table"
          aria-label="Logistics routes"
        >
          <tbody>
            {detail.routes.map((r: Route) => (
              <tr key={r.id} data-route={r.code}>
                <td>
                  {r.label}
                  {r.detail && <div className="nx-dim">{r.detail}</div>}
                  {r.zone_incidents.length > 0 && (
                    <div className="nx-dim">
                      Through impact zone · {r.zone_incidents.join(", ")}
                    </div>
                  )}
                </td>
                <td className="nx-ev-right">
                  <Sev status={r.shown} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}

/** Supply Chain Risk (SUP-01..06; D-44). Suppliers, routes and statuses are simulated (D-19). */
export function SupplyScreen() {
  const [params, setParams] = useSearchParams();
  const missions = [...(useMissions().data ?? [])].sort((a, b) =>
    a.code.localeCompare(b.code),
  );
  const summary = useSupplySummary().data;
  const chosen = params.get("mission");
  const missionId =
    chosen ??
    (missions.length && summary ? defaultSupplyMission(missions, summary) : "");
  const suppliers = useSuppliers(missionId);
  const rows = suppliers.data ?? [];
  const [picked, setPicked] = useState<string>();
  const selected =
    rows.find((s) => s.id === picked) ??
    rows.find((s) => s.impacted) ??
    rows[0];
  const detail = useSupplier(selected?.id).data;
  const impactedCities = new Set(
    (summary?.impacted_missions ?? []).map(
      (code) => missions.find((m) => m.code === code)?.city ?? code,
    ),
  );

  return (
    <div className="nx-pad">
      <div className="nx-row nx-mb nx-ev-picker">
        <span className="nx-dim">Mission</span>
        <HTMLSelect
          minimal
          aria-label="Mission"
          value={missionId}
          onChange={(e) => {
            setPicked(undefined);
            setParams({ mission: e.currentTarget.value });
          }}
          options={[
            { value: "", label: "All missions" },
            ...missions.map((m) => ({
              value: m.id,
              label: `${m.code} · ${m.city}`,
            })),
          ]}
        />
        <span className="nx-grow" />
        <span className="nx-dim">
          Illustrative supplier register (simulated)
        </span>
      </div>
      <ImpactBanner banners={summary?.banners ?? []} />
      <div className="nx-g4 nx-mb">
        <Kpi
          icon="box"
          label="Third parties monitored"
          value={summary?.suppliers ?? "—"}
          detail={summary ? `Across ${summary.missions} missions` : undefined}
        />
        <Kpi
          icon="shield"
          label="Critical (Tier 1) suppliers"
          value={summary?.tier1 ?? "—"}
          detail="Single points of failure mapped"
        />
        <Kpi
          icon="warning-sign"
          label="Impacted now"
          value={summary?.impacted ?? "—"}
          detail={
            !summary?.impacted
              ? "No active disruption"
              : impactedCities.size === 1
                ? `All in ${[...impactedCities][0]}`
                : `${impactedCities.size} missions`
          }
          alert={!!summary?.impacted}
        />
        <Kpi
          icon="route"
          label="Routes monitored"
          value={summary?.routes ?? "—"}
          detail="Courier, fuel, staff transport"
        />
      </div>
      <div className="nx-ev-grid nx-sup-grid">
        <SuppliersCard
          suppliers={rows}
          loading={suppliers.isLoading}
          selected={selected?.id}
          onSelect={setPicked}
          total={summary?.suppliers}
        />
        <div className="nx-col">
          {detail && <SupplierCard key={detail.id} detail={detail} />}
          {detail && <RoutesCard detail={detail} />}
        </div>
      </div>
    </div>
  );
}
