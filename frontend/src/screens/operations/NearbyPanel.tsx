import { Button, ButtonGroup, NonIdealState, Spinner } from "@blueprintjs/core";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { annotationWhat, type AnnotationKind, type AnnotationSymbol } from "../../api/annotations";
import { distanceText, type Near, RADII_KM, useNearby } from "../../api/nearby";
import { Card, Sev } from "../../ui/primitives";

// Nearby on Global Operations (NBY-01..06; D-52; plan-pilot-map §3): what is within the chosen
// radius of a point, nearest first. Each row flies the map to it; an incident opens its impact
// panel. Names only within the caller's people scope (the API decides); counts for everyone.

const GROUP_LABEL = { STAFF: "Staff", DELEGATE: "Delegate", CITIZEN: "Citizen", OTHER: "Other" } as const;

function Section({ title, count, children }: { title: string; count: number; children: ReactNode }) {
  return (
    <section className="nx-near-section" aria-label={title}>
      <h4>
        {title} <span className="nx-dim">{count}</span>
      </h4>
      {count === 0 ? <div className="nx-dim">None in range</div> : children}
    </section>
  );
}

function Row({ onClick, children, distance }: { onClick: () => void; children: ReactNode; distance: number }) {
  return (
    <li>
      <button type="button" className="nx-near-row" onClick={onClick}>
        <span>{children}</span>
        <span className="nx-dim nx-mono">{distanceText(distance)}</span>
      </button>
    </li>
  );
}

export function NearbyPanel({
  near,
  onRadius,
  onClose,
  onFly,
  onIncident,
}: {
  near: Near;
  onRadius: (km: number) => void;
  onClose: () => void;
  onFly: (lon: number, lat: number) => void;
  onIncident: (id: string) => void;
}) {
  const { data, isPending, isError } = useNearby(near);
  return (
    <Card
      icon="locate"
      title="What's nearby"
      className="nx-side nx-near"
      actions={<Button size="small" text="Feed" onClick={onClose} />}
    >
      <div className="nx-near-wrap" aria-label="What's nearby">
      <div className="nx-near-head">
        <span className="nx-dim nx-mono">
          {near.lat.toFixed(4)}, {near.lon.toFixed(4)}
        </span>
        <ButtonGroup aria-label="Radius">
          {RADII_KM.map((km) => (
            <Button key={km} small text={`${km} km`} active={near.km === km} onClick={() => onRadius(km)} />
          ))}
        </ButtonGroup>
      </div>
      {isError ? (
        <NonIdealState icon="error" title="Nearby could not be loaded" />
      ) : isPending || !data ? (
        <Spinner size={20} />
      ) : (
        <div className="nx-near-body">
          <Section
            title="People"
            count={data.people.staff + data.people.delegates + data.people.citizens + data.people.others}
          >
            <div className="nx-near-counts">
              <span><b>{data.people.staff}</b> staff</span>
              <span><b>{data.people.delegates}</b> delegates</span>
              <span><b>{data.people.citizens}</b> citizens</span>
              <span><b>{data.people.others}</b> {data.people.others === 1 ? "other" : "others"}</span>
              {data.people.confidence !== null && (
                <span className="nx-dim">{data.people.confidence}% avg. confidence</span>
              )}
            </div>
            <ul className="nx-near-list">
              {data.people.named.map((p) => (
                <Row key={p.id} distance={p.distance_m} onClick={() => onFly(p.lon, p.lat)}>
                  {p.name} <span className="nx-dim">· {GROUP_LABEL[p.group]}</span>
                </Row>
              ))}
            </ul>
            {data.people.unnamed > 0 && (
              <div className="nx-dim">{data.people.unnamed} more not named for your role</div>
            )}
          </Section>
          <Section title="Incidents" count={data.incidents.length}>
            <ul className="nx-near-list">
              {data.incidents.map((i) => (
                <Row key={i.id} distance={i.distance_m} onClick={() => onIncident(i.id)}>
                  <Sev severity={i.severity} /> {i.reference} · {i.title}
                </Row>
              ))}
            </ul>
          </Section>
          <Section title="Sites" count={data.sites.length}>
            <ul className="nx-near-list">
              {data.sites.map((s) => (
                <Row key={s.id} distance={s.distance_m} onClick={() => onFly(s.lon, s.lat)}>
                  {s.name}
                </Row>
              ))}
            </ul>
          </Section>
          <Section title="Vehicles" count={data.vehicles.length}>
            <ul className="nx-near-list">
              {data.vehicles.map((v) => (
                <Row key={v.id} distance={v.distance_m} onClick={() => onFly(v.lon, v.lat)}>
                  {v.code} · {v.type_label} <span className="nx-dim">· {v.status.toLowerCase().replace("_", " ")}</span>
                </Row>
              ))}
            </ul>
          </Section>
          <Section title="Travellers in transit" count={data.travellers.people}>
            <div className="nx-near-counts">
              <span>
                <b>{data.travellers.people}</b> on <b>{data.travellers.trips}</b> trip
                {data.travellers.trips === 1 ? "" : "s"}
              </span>
              <Link to="/journeys">Journey Management</Link>
            </div>
          </Section>
          <Section title="Annotations" count={data.annotations.length}>
            <ul className="nx-near-list">
              {data.annotations.map((a) => (
                <Row key={a.id} distance={a.distance_m} onClick={() => onFly(a.lon, a.lat)}>
                  {annotationWhat({ kind: a.kind as AnnotationKind, symbol: a.symbol as AnnotationSymbol | null })} ·{" "}
                  {a.label}
                </Row>
              ))}
            </ul>
          </Section>
          <Section title={`Partners${data.country_code ? ` covering ${data.country_code}` : ""}`} count={data.partners.length}>
            <ul className="nx-near-list">
              {data.partners.map((p) => (
                <li key={p.id}>
                  <Link className="nx-near-row" to="/partners">
                    <span>{p.name}</span>
                    <span className="nx-dim">SLA {p.sla_minutes} min</span>
                  </Link>
                </li>
              ))}
            </ul>
          </Section>
        </div>
      )}
      </div>
    </Card>
  );
}
