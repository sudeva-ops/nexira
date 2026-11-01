import { Button, HTMLSelect, Icon, NonIdealState } from "@blueprintjs/core";
import { useNavigate, useSearchParams } from "react-router-dom";

import { ApiError } from "../../api/client";
import {
  type Advisory,
  defaultMission,
  distanceText,
  type Facility,
  missionAdvisories,
  type MissionHealth,
  type Readiness,
  type Requirement,
  topicWord,
  useAdvisories,
  useCreateHealthCampaign,
  useHealthPermissions,
  useHealthSummary,
  useMissionHealth,
  useRequirements,
} from "../../api/health";
import type { Severity } from "../../api/intel";
import { type Mission, useMissions } from "../../api/people";
import { formatStamp } from "../../app/time";
import { FlashRow } from "../../ui/motion";
import { Card, Kpi, Sev } from "../../ui/primitives";
import { SkeletonRows } from "../../ui/Skeleton";

const LEVEL_WORD: Record<Severity, string> = { CRITICAL: "Critical", HIGH: "High", MODERATE: "Moderate", LOW: "Low" };

function affectsText(a: Advisory): string | null {
  if (a.missions.length === 0) return null;
  const cities = a.missions.map((m) => m.city);
  return `Affects ${cities.join(", ")} mission${cities.length === 1 ? "" : "s"}`;
}

function AdvisoryRow({ a }: { a: Advisory }) {
  const affects = a.status === "OPEN" ? affectsText(a) : null;
  return (
    <FlashRow data-advisory={a.reference} watch={`${a.level} ${a.status} ${a.updated_at}`}>
      <td>
        <b>{a.topic}</b>
        {affects && <div className="nx-hl-affects">{affects}</div>}
        <div className="nx-dim">
          {a.reference} · {a.source}
        </div>
      </td>
      <td>{a.region_label}</td>
      <td>{a.status === "OPEN" ? <Sev severity={a.level} /> : <span className="nx-sev ok">CLOSED</span>}</td>
      <td className="nx-mono nx-dim nx-hl-stamp">{formatStamp(a.published_at)}</td>
      <td className="nx-hl-guidance">{a.guidance}</td>
    </FlashRow>
  );
}

function AdvisoriesCard({ advisories, loading }: { advisories: Advisory[]; loading: boolean }) {
  return (
    <Card icon="warning-sign" title="Outbreak & health advisories" sub="WHO DON · ministry bulletins · partner intel (simulated)">
      {loading ? (
        <SkeletonRows />
      ) : advisories.length === 0 ? (
        <NonIdealState icon="heart" title="No health advisories" description="Nothing open or closed in the last 7 days." />
      ) : (
        <table className="nx-table-plain nx-hl-table" aria-label="Health advisories">
          <thead>
            <tr>
              <th>Event</th>
              <th>Location</th>
              <th>Level</th>
              <th>Published</th>
              <th>Guidance for staff</th>
            </tr>
          </thead>
          <tbody>
            {advisories.map((a) => (
              <AdvisoryRow key={a.id} a={a} />
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}

function RequirementsCard({ rows, missions, loading }: { rows: Requirement[]; missions: Mission[]; loading: boolean }) {
  const cities = (country: string) =>
    missions
      .filter((m) => m.country_code === country)
      .map((m) => m.city)
      .join(", ");
  return (
    <Card icon="document" title="Entry & vaccination requirements" sub="Mission countries · illustrative (simulated)">
      {loading ? (
        <SkeletonRows />
      ) : (
        <div className="nx-hl-scroll">
          <table className="nx-table-plain nx-hl-table" aria-label="Entry requirements">
            <thead>
              <tr>
                <th>Country</th>
                <th>Mandatory</th>
                <th>Recommended</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.country_code}>
                  <td className="nx-nowrap">
                    <b>{r.country_code}</b>
                    <div className="nx-dim">{cities(r.country_code)}</div>
                  </td>
                  <td>{r.mandatory}</td>
                  <td>{r.recommended}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

// backend/migrations/sql/0009_health.sql: medical_facility.capabilities.
const CAPABILITY: Record<string, string> = {
  EMERGENCY: "Emergency",
  TRAUMA: "Trauma",
  ICU: "ICU",
  SURGERY: "Surgery",
  HELIPAD: "Helipad",
  PHARMACY: "Pharmacy",
  OUTPATIENT: "Outpatient",
  MATERNITY: "Maternity",
  PAEDIATRIC: "Paediatric",
};

function facilityText(f: Facility): string {
  const parts = f.capabilities.map((c) =>
    c === "TRAUMA" && f.trauma_level !== null ? `Trauma level ${f.trauma_level}` : (CAPABILITY[c] ?? c),
  );
  if (f.open_24_7) parts.push("24/7");
  return parts.join(" · ");
}

function FacilityRow({ f }: { f: Facility }) {
  return (
    <FlashRow data-facility={f.name} watch={`${f.avoid}`} tone={f.avoid ? "danger" : "success"}>
      <td>
        <b>{f.name}</b>
        <div className="nx-dim">{facilityText(f)}</div>
        <div className="nx-dim">{f.vetted_by ? `Vetted by ${f.vetted_by}` : "Not vetted"}</div>
        {f.avoid && (
          <div className="nx-hl-affects">
            Avoid · inside impact zone{f.avoid_incident && ` of ${f.avoid_incident}`}
          </div>
        )}
      </td>
      <td className="nx-mono nx-dim nx-nowrap">{distanceText(f.distance_m)}</td>
      <td>{f.avoid ? <Sev severity="CRITICAL" label="AVOID" /> : <span className="nx-sev ok">OPEN</span>}</td>
    </FlashRow>
  );
}

function Tick({ done, label, detail }: { done: boolean; label: string; detail?: string }) {
  return (
    <div className="nx-row nx-hl-tick">
      <Icon icon={done ? "tick-circle" : "issue"} size={13} className={done ? "nx-hl-done" : "nx-hl-due"} />
      <span className="nx-grow">{label}</span>
      {detail && <span className="nx-mono nx-dim">{detail}</span>}
    </div>
  );
}

function ReadinessCard({ city, r, topics }: { city: string; r: Readiness | null; topics: Map<string, string> }) {
  return (
    <Card icon="people" title={`Staff health readiness · ${city}`} sub="Counts only (D-39)">
      {!r ? (
        <div className="nx-bd nx-dim">No readiness counts for this mission.</div>
      ) : (
        <div className="nx-bd" aria-label="Staff health readiness">
          <Tick
            done={r.blood_type_on_file === r.staff}
            label="Blood type on file"
            detail={`${r.blood_type_on_file} / ${r.staff}`}
          />
          <Tick
            done={r.insurance_active === r.staff}
            label="Medical insurance active"
            detail={`${r.insurance_active} / ${r.staff}`}
          />
          {r.vaccines
            .filter((v) => v.open_advisory)
            .map((v) => (
              <Tick
                key={v.topic_code}
                done={v.offered === r.staff}
                label={`${topics.get(v.topic_code) ?? topicWord(v.topic_code)} vaccine offered`}
                detail={`${v.offered} / ${r.staff}`}
              />
            ))}
          <Tick done={r.trauma_kits > 0} label={`Trauma kits at mission (${r.trauma_kits})`} />
          <div className="nx-dim nx-hl-asof">
            As of {r.as_of} · {r.source}
          </div>
        </div>
      )}
    </Card>
  );
}

/** HL-06: shown only when GET /api/me/permissions allows it; the backend decides. */
function SendCard({ health, advisory }: { health: MissionHealth; advisory: Advisory | undefined }) {
  const allowed = useHealthPermissions(health.mission_id).data?.send_advisory;
  const create = useCreateHealthCampaign();
  const navigate = useNavigate();
  if (!allowed || !advisory) return null;
  const send = () =>
    create.mutate(
      { advisoryId: advisory.id, missionId: health.mission_id },
      { onSuccess: (c) => navigate(`/notifications?campaign=${c.campaign_id}`) },
    );
  return (
    <Card icon="send-message" title="Health advisory" sub={`${advisory.topic} · ${advisory.reference}`}>
      <div className="nx-bd">
        <Button
          intent="primary"
          icon="send-message"
          text={`Send health advisory to ${health.city}`}
          loading={create.isPending}
          onClick={send}
        />
        <div className="nx-dim nx-hl-asof">
          Opens a draft for the mission&apos;s staff and registered citizens on Mass Notification; a second person
          approves it (D-31).
        </div>
        {create.isError && (
          <div className="nx-error">{create.error instanceof ApiError ? create.error.message : "Not done"}</div>
        )}
      </div>
    </Card>
  );
}

function MissionPanel({
  missionId,
  missions,
  onPick,
  advisory,
  topics,
}: {
  missionId: string | undefined;
  missions: Mission[];
  onPick: (id: string) => void;
  advisory: Advisory | undefined;
  topics: Map<string, string>;
}) {
  const health = useMissionHealth(missionId);
  const data = health.data;
  const city = data?.city ?? missions.find((m) => m.id === missionId)?.city ?? "—";
  return (
    <div className="nx-col">
      <Card
        icon="heart"
        title={`Medical facilities · ${city}`}
        sub="Nearest to mission (simulated)"
        actions={
          <HTMLSelect
            minimal
            aria-label="Mission"
            value={missionId ?? ""}
            onChange={(e) => onPick(e.currentTarget.value)}
            options={missions.map((m) => ({ value: m.id, label: `${m.code} · ${m.city}` }))}
          />
        }
      >
        {health.isLoading || !data ? (
          <SkeletonRows />
        ) : data.facilities.length === 0 ? (
          <div className="nx-bd nx-dim">No facilities recorded for this mission.</div>
        ) : (
          <table className="nx-table-plain nx-hl-table" aria-label="Medical facilities">
            <thead>
              <tr>
                <th>Facility</th>
                <th>Distance</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {data.facilities.map((f) => (
                <FacilityRow key={f.id} f={f} />
              ))}
            </tbody>
          </table>
        )}
      </Card>
      {data && <ReadinessCard city={data.city} r={data.readiness} topics={topics} />}
      {data && <SendCard health={data} advisory={advisory} />}
    </div>
  );
}

/** Health Intelligence (HL-01..09; D-39). Advisories and counts are simulated (D-19); no person-level data. */
export function HealthScreen() {
  const [params, setParams] = useSearchParams();
  const advisories = useAdvisories();
  const summary = useHealthSummary().data;
  const requirements = useRequirements();
  const missions = [...(useMissions().data ?? [])].sort((a, b) => a.code.localeCompare(b.code));
  const list = advisories.data ?? [];
  const byMission = missionAdvisories(list);
  const missionId = params.get("mission") ?? (advisories.data ? defaultMission(list, missions) : undefined);
  const topics = new Map(list.map((a) => [a.topic_code, a.topic]));

  return (
    <div className="nx-pad">
      <div className="nx-banner nx-mb" role="note">
        <Icon icon="heart" />
        <div>
          <b>
            Health intelligence fused from WHO Disease Outbreak News, national health ministries and medical-assistance
            partners.
          </b>{" "}
          Simulated samples for demonstration.
        </div>
      </div>
      <div className="nx-g4 nx-mb">
        <Kpi
          icon="warning-sign"
          label="Open health advisories"
          value={summary ? summary.open_advisories : "—"}
          detail={summary && `${summary.affecting_missions} affecting mission countries`}
        />
        <Kpi
          icon="office"
          label="Missions with an advisory"
          value={summary ? summary.missions_with_advisory : "—"}
          detail={
            summary &&
            (summary.by_level.map((l) => `${l.missions} ${LEVEL_WORD[l.level]}`).join(" · ") || "None")
          }
          alert={summary?.by_level.some((l) => l.level === "CRITICAL" || l.level === "HIGH")}
        />
        <Kpi
          icon="people"
          label="Staff not yet offered a vaccine"
          value={summary ? summary.staff_not_offered : "—"}
          detail="For open advisories in their country"
        />
        <Kpi
          icon="heart"
          label="Vetted facilities"
          value={summary ? summary.vetted_facilities : "—"}
          detail="Vetted by an assistance partner"
        />
      </div>
      <div className="nx-hl-grid">
        <div className="nx-col">
          <AdvisoriesCard advisories={list} loading={advisories.isLoading} />
          <RequirementsCard rows={requirements.data ?? []} missions={missions} loading={requirements.isLoading} />
        </div>
        <MissionPanel
          missionId={missionId}
          missions={missions}
          onPick={(id) => setParams({ mission: id })}
          advisory={missionId ? byMission.get(missionId) : undefined}
          topics={topics}
        />
      </div>
    </div>
  );
}
