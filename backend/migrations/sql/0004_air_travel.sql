-- Pilot module 3, Air Travel Tracking (D-33): PC-17, PC-18 and PC-19, approved by the
-- product owner on 2026-10-27 (PR #30), with the plan's answers (docs/plan-pilot-air.md,
-- PR #31). Runs as nexira_owner (D-01). RLS and grants: named human sign-off (D-29).

-- PC-18 · simulated airports (D-19).
CREATE TABLE airport (
  tenant_id     uuid NOT NULL REFERENCES tenant(id),
  iata          char(3) NOT NULL CHECK (iata ~ '^[A-Z]{3}$'),
  name          text NOT NULL,
  city          text NOT NULL,
  country_code  char(2) NOT NULL,
  location      geography(Point,4326) NOT NULL,
  PRIMARY KEY (tenant_id, iata)
);
ALTER TABLE airport ENABLE ROW LEVEL SECURITY;
ALTER TABLE airport FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON airport
  USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());
-- INSERT for the seed, which loads through the service layer as nexira_api (plan Q10).
GRANT SELECT, INSERT ON airport TO nexira_app;

-- PC-17 · flight details on a segment (frozen with the segment by trip_child_guard).
-- The composite keys keep an airport in the segment's own tenant (plan G-6).
ALTER TABLE trip_segment
  ADD COLUMN flight_number text CHECK (flight_number ~ '^[A-Z0-9]{2} ?[0-9]{1,4}[A-Z]?$'),
  ADD COLUMN from_airport  char(3),
  ADD COLUMN to_airport    char(3),
  ADD CONSTRAINT trip_segment_from_airport_fk FOREIGN KEY (tenant_id, from_airport)
    REFERENCES airport (tenant_id, iata),
  ADD CONSTRAINT trip_segment_to_airport_fk FOREIGN KEY (tenant_id, to_airport)
    REFERENCES airport (tenant_id, iata),
  ADD CONSTRAINT trip_segment_flight_check
    CHECK (kind = 'FLIGHT' OR (flight_number IS NULL AND from_airport IS NULL AND to_airport IS NULL));

-- PC-17 · restricted (VIP or ministerial) trips: never tracked (D-33), fixed once the
-- trip leaves DRAFT. A separate trigger, so trip_guard (0003) stays as reviewed.
ALTER TABLE trip ADD COLUMN restricted boolean NOT NULL DEFAULT false;
CREATE FUNCTION trip_restricted_guard() RETURNS trigger AS $$
BEGIN
  IF NEW.restricted IS DISTINCT FROM OLD.restricted AND OLD.approval_status <> 'DRAFT' THEN
    RAISE EXCEPTION 'trip: the trip is frozen once it leaves DRAFT';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER trip_restricted_guard BEFORE UPDATE ON trip
  FOR EACH ROW EXECUTE FUNCTION trip_restricted_guard();

-- PC-19 · tracked flights, written only by the tracker (and the seed, plan G-3).
CREATE TABLE flight (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenant(id),
  trip_segment_id uuid NOT NULL UNIQUE REFERENCES trip_segment(id) ON DELETE CASCADE,
  flight_number   text NOT NULL,
  from_airport    char(3) NOT NULL,
  to_airport      char(3) NOT NULL,
  scheduled_dep   timestamptz NOT NULL,
  scheduled_arr   timestamptz NOT NULL,
  estimated_dep   timestamptz NOT NULL,
  estimated_arr   timestamptz NOT NULL,
  status          text NOT NULL DEFAULT 'SCHEDULED'
                  CHECK (status IN ('SCHEDULED','DELAYED','AIRBORNE','HOLDING','DIVERTED','LANDED','CANCELLED')),
  diverted_to     char(3),
  position        geography(Point,4326),
  altitude_ft     integer CHECK (altitude_ft >= 0),
  speed_kt        integer CHECK (speed_kt >= 0),
  source          text NOT NULL DEFAULT 'SIMULATED' CHECK (source IN ('SIMULATED','SCENARIO')),
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (tenant_id, from_airport) REFERENCES airport (tenant_id, iata),
  FOREIGN KEY (tenant_id, to_airport) REFERENCES airport (tenant_id, iata),
  FOREIGN KEY (tenant_id, diverted_to) REFERENCES airport (tenant_id, iata),
  CHECK (scheduled_arr >= scheduled_dep),
  CHECK (estimated_arr >= estimated_dep),
  CHECK (status <> 'DIVERTED' OR diverted_to IS NOT NULL)
);
CREATE INDEX flight_status_idx ON flight (tenant_id, status);
ALTER TABLE flight ENABLE ROW LEVEL SECURITY;
ALTER TABLE flight FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON flight
  USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());
GRANT SELECT, INSERT, UPDATE ON flight TO nexira_app;

CREATE TABLE flight_event (
  id           bigserial PRIMARY KEY,
  tenant_id    uuid NOT NULL REFERENCES tenant(id),
  flight_id    uuid NOT NULL REFERENCES flight(id) ON DELETE CASCADE,
  event_type   text NOT NULL
               CHECK (event_type IN ('DEPARTED','DELAYED','HOLDING','DIVERTED','LANDED','CANCELLED')),
  occurred_at  timestamptz NOT NULL DEFAULT now(),
  details      jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(details) = 'object')
);
CREATE INDEX flight_event_flight_idx ON flight_event (flight_id, occurred_at);
ALTER TABLE flight_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE flight_event FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON flight_event
  USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());
-- Append-only: no UPDATE or DELETE grant.
GRANT SELECT, INSERT ON flight_event TO nexira_app;
GRANT USAGE ON SEQUENCE flight_event_id_seq TO nexira_app;

-- The database backstop for D-33. A flight exists only for a FLIGHT segment of an
-- APPROVED trip that is not restricted, and matches that segment; it starts SCHEDULED;
-- identity and schedule never change; status follows the plan's table (G-8).
CREATE FUNCTION flight_guard() RETURNS trigger AS $$
DECLARE
  s record;
BEGIN
  IF TG_OP = 'INSERT' THEN
    SELECT seg.tenant_id, seg.kind, seg.flight_number, seg.from_airport, seg.to_airport,
           t.approval_status, t.restricted
      INTO s
      FROM trip_segment seg JOIN trip t ON t.id = seg.trip_id
     WHERE seg.id = NEW.trip_segment_id
       FOR SHARE OF t;
    IF NOT FOUND OR s.tenant_id <> NEW.tenant_id THEN
      RAISE EXCEPTION 'flight: no such segment';
    END IF;
    IF s.restricted THEN
      RAISE EXCEPTION 'flight: a restricted trip is never tracked (D-33)';
    END IF;
    IF s.approval_status <> 'APPROVED' THEN
      RAISE EXCEPTION 'flight: only an approved trip is tracked (D-33)';
    END IF;
    IF s.kind <> 'FLIGHT' OR s.flight_number IS DISTINCT FROM NEW.flight_number
       OR s.from_airport IS DISTINCT FROM NEW.from_airport
       OR s.to_airport IS DISTINCT FROM NEW.to_airport THEN
      RAISE EXCEPTION 'flight: the flight must match its segment';
    END IF;
    IF NEW.status <> 'SCHEDULED' OR NEW.diverted_to IS NOT NULL THEN
      RAISE EXCEPTION 'flight: a flight starts SCHEDULED';
    END IF;
    NEW.created_at := now();
    NEW.updated_at := now();
    RETURN NEW;
  END IF;

  IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
     OR NEW.trip_segment_id IS DISTINCT FROM OLD.trip_segment_id
     OR NEW.flight_number IS DISTINCT FROM OLD.flight_number
     OR NEW.from_airport IS DISTINCT FROM OLD.from_airport
     OR NEW.to_airport IS DISTINCT FROM OLD.to_airport
     OR NEW.scheduled_dep IS DISTINCT FROM OLD.scheduled_dep
     OR NEW.scheduled_arr IS DISTINCT FROM OLD.scheduled_arr
     OR NEW.source IS DISTINCT FROM OLD.source
     OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'flight: identity and schedule cannot change';
  END IF;
  IF OLD.status IN ('LANDED','CANCELLED') THEN
    RAISE EXCEPTION 'flight: a % flight is final', OLD.status;
  END IF;
  IF NEW.status IS DISTINCT FROM OLD.status AND NOT (
       (OLD.status = 'SCHEDULED' AND NEW.status IN ('DELAYED','AIRBORNE','CANCELLED'))
       OR (OLD.status = 'DELAYED' AND NEW.status IN ('AIRBORNE','CANCELLED'))
       OR (OLD.status = 'AIRBORNE' AND NEW.status IN ('HOLDING','DIVERTED','LANDED'))
       OR (OLD.status = 'HOLDING' AND NEW.status IN ('AIRBORNE','DIVERTED','LANDED'))
       OR (OLD.status = 'DIVERTED' AND NEW.status IN ('HOLDING','LANDED'))) THEN
    RAISE EXCEPTION 'flight: status cannot go from % to %', OLD.status, NEW.status;
  END IF;
  IF NEW.diverted_to IS DISTINCT FROM OLD.diverted_to
     AND NOT (NEW.status = 'DIVERTED' AND OLD.status <> 'DIVERTED') THEN
    RAISE EXCEPTION 'flight: the diversion airport is set only by diverting';
  END IF;
  NEW.updated_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER flight_guard BEFORE INSERT OR UPDATE ON flight
  FOR EACH ROW EXECUTE FUNCTION flight_guard();

-- An event belongs to a flight in its own tenant (FKs ignore RLS).
CREATE FUNCTION flight_event_guard() RETURNS trigger AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM flight WHERE id = NEW.flight_id AND tenant_id = NEW.tenant_id) THEN
    RAISE EXCEPTION 'flight: no such flight';
  END IF;
  NEW.occurred_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER flight_event_guard BEFORE INSERT ON flight_event
  FOR EACH ROW EXECUTE FUNCTION flight_event_guard();
