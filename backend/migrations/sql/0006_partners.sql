-- Pilot module 5, Assistance Partners (D-36): PC-21 and PC-22, approved by the product
-- owner on 2026-10-30 (PR #49), with the plan's answers (docs/plan-pilot-ast.md, PR #50).
-- Runs as nexira_owner (D-01). RLS and grants: named human sign-off (D-29).

-- PC-21 · the partner directory: fictional, simulated partners (D-19), seeded through the
-- service layer as nexira_api. No UPDATE or DELETE in the pilot.
CREATE TABLE partner (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    uuid NOT NULL REFERENCES tenant(id),
  code         text NOT NULL CHECK (code ~ '^[A-Z]{2,10}$'),
  name         text NOT NULL CHECK (length(name) BETWEEN 1 AND 100),
  -- One-dimensional, no NULLs (a NULL would make "= ANY" unknown: review of Prompt 44, M1).
  services     text[] NOT NULL CHECK (
                 cardinality(services) > 0 AND array_ndims(services) = 1
                 AND array_position(services, NULL) IS NULL
                 AND services <@ ARRAY['MEDICAL','EVACUATION','SECURE_TRANSPORT','WELFARE','RELOCATION']
               ),
  coverage     char(2)[] NOT NULL CHECK (
                 cardinality(coverage) > 0 AND array_ndims(coverage) = 1
                 AND array_position(coverage, NULL) IS NULL
                 AND array_to_string(coverage, ',') ~ '^[A-Z]{2}(,[A-Z]{2})*$'
               ),
  sla_minutes  integer NOT NULL CHECK (sla_minutes BETWEEN 1 AND 10080),
  hours        text NOT NULL DEFAULT '24/7' CHECK (length(hours) BETWEEN 1 AND 50),
  is_active    boolean NOT NULL DEFAULT true,
  created_at   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, code)
);
ALTER TABLE partner ENABLE ROW LEVEL SECURITY;
ALTER TABLE partner FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON partner
  USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());
GRANT SELECT, INSERT ON partner TO nexira_app;

-- PC-22 · requests to partners and their tracking (AS-02..06, AS-08). No DELETE.
CREATE TABLE partner_request (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL REFERENCES tenant(id),
  reference        text NOT NULL CHECK (reference ~ '^REQ-[0-9]+$'),  -- next_reference('REQ', false)
  partner_id       uuid NOT NULL REFERENCES partner(id),
  service          text NOT NULL
                   CHECK (service IN ('MEDICAL','EVACUATION','SECURE_TRANSPORT','WELFARE','RELOCATION')),
  mission_id       uuid NOT NULL REFERENCES mission(id),
  incident_id      uuid REFERENCES incident(id),
  person_id        uuid REFERENCES person(id),
  place_label      text CHECK (length(place_label) <= 200),
  location         geography(Point,4326),
  note             text CHECK (length(note) <= 500),
  status           text NOT NULL DEFAULT 'REQUESTED' CHECK (
                     status IN ('REQUESTED','ACCEPTED','EN_ROUTE','COMPLETED','DECLINED','CANCELLED')
                   ),
  eta              timestamptz,
  created_by_type  text NOT NULL CHECK (created_by_type IN ('USER','PLAYBOOK')),
  created_by       text NOT NULL CHECK (length(created_by) BETWEEN 1 AND 100),
  requested_at     timestamptz NOT NULL DEFAULT now(),
  accepted_at      timestamptz,
  completed_at     timestamptz,
  updated_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, reference),
  -- Accepted (and later) requests have their acceptance time; a cancelled one may or may not.
  CHECK (CASE WHEN status IN ('ACCEPTED','EN_ROUTE','COMPLETED') THEN accepted_at IS NOT NULL
              WHEN status IN ('REQUESTED','DECLINED') THEN accepted_at IS NULL
              ELSE true END),
  CHECK ((status = 'COMPLETED') = (completed_at IS NOT NULL)),
  -- An accepted request has an ETA, never before it was made (review of Prompt 44, N7).
  CHECK (status NOT IN ('ACCEPTED','EN_ROUTE') OR eta IS NOT NULL),
  CHECK (eta IS NULL OR eta >= requested_at)
);
CREATE INDEX partner_request_status_idx ON partner_request (tenant_id, status);
CREATE INDEX partner_request_incident_idx ON partner_request (incident_id);
ALTER TABLE partner_request ENABLE ROW LEVEL SECURITY;
ALTER TABLE partner_request FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON partner_request
  USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());
-- Only status and ETA move (review of Prompt 44, M3); the trigger writes the timestamps.
GRANT SELECT, INSERT ON partner_request TO nexira_app;
GRANT UPDATE (status, eta) ON partner_request TO nexira_app;

-- The request rules (plan-pilot-ast.md §2, §7, §10, G-5). Foreign keys ignore RLS, so the
-- tenant of every reference is checked here (the lesson of Prompts 24 and 29). The trigger
-- runs as the caller, so RLS already hides other tenants' rows; the tenant_id conditions
-- keep the rules true for a role that bypasses RLS. search_path pinned, pg_temp last (the
-- lesson of Prompt 39).
CREATE FUNCTION partner_request_guard() RETURNS trigger AS $$
DECLARE
  p        partner%ROWTYPE;
  country  char(2);
BEGIN
  IF TG_OP = 'UPDATE' THEN
    -- Content is fixed once requested; only status and ETA move.
    IF (NEW.id, NEW.tenant_id, NEW.reference, NEW.partner_id, NEW.service, NEW.mission_id,
        NEW.incident_id, NEW.person_id, NEW.place_label, NEW.location::text, NEW.note,
        NEW.created_by_type, NEW.created_by, NEW.requested_at)
       IS DISTINCT FROM
       (OLD.id, OLD.tenant_id, OLD.reference, OLD.partner_id, OLD.service, OLD.mission_id,
        OLD.incident_id, OLD.person_id, OLD.place_label, OLD.location::text, OLD.note,
        OLD.created_by_type, OLD.created_by, OLD.requested_at) THEN
      RAISE EXCEPTION 'partner request: its content is fixed once requested';
    END IF;
    IF NEW.accepted_at IS DISTINCT FROM OLD.accepted_at
       OR NEW.completed_at IS DISTINCT FROM OLD.completed_at THEN
      RAISE EXCEPTION 'partner request: its timestamps are written by the database';
    END IF;
    IF NEW.status IS DISTINCT FROM OLD.status THEN
      IF NOT (
        (OLD.status = 'REQUESTED' AND NEW.status IN ('ACCEPTED','DECLINED','CANCELLED'))
        OR (OLD.status = 'ACCEPTED' AND NEW.status IN ('EN_ROUTE','CANCELLED'))
        OR (OLD.status = 'EN_ROUTE' AND NEW.status IN ('COMPLETED','CANCELLED'))
      ) THEN
        RAISE EXCEPTION 'partner request: % cannot become %', OLD.status, NEW.status;
      END IF;
      IF NEW.status = 'ACCEPTED' THEN
        NEW.accepted_at := now();
      ELSIF NEW.status = 'COMPLETED' THEN
        NEW.completed_at := now();
      END IF;
    END IF;
    IF NEW.eta IS DISTINCT FROM OLD.eta AND NEW.status NOT IN ('ACCEPTED','EN_ROUTE') THEN
      RAISE EXCEPTION 'partner request: an ETA is set only once accepted';
    END IF;
    NEW.updated_at := now();
    RETURN NEW;
  END IF;

  -- INSERT: a new request, in its own tenant, to a partner that can help there.
  IF NEW.status <> 'REQUESTED' OR NEW.eta IS NOT NULL
     OR NEW.accepted_at IS NOT NULL OR NEW.completed_at IS NOT NULL THEN
    RAISE EXCEPTION 'partner request: a request starts as REQUESTED';
  END IF;
  NEW.requested_at := now();
  NEW.updated_at := now();
  SELECT * INTO p FROM partner WHERE id = NEW.partner_id AND tenant_id = NEW.tenant_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'partner request: no such partner';
  END IF;
  SELECT m.country_code INTO country FROM mission m
   WHERE m.id = NEW.mission_id AND m.tenant_id = NEW.tenant_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'partner request: no such mission';
  END IF;
  IF NOT p.is_active THEN
    RAISE EXCEPTION 'partner request: % is not active', p.code;
  END IF;
  IF NOT coalesce(NEW.service = ANY (p.services), false) THEN
    RAISE EXCEPTION 'partner request: % does not offer %', p.code, NEW.service;
  END IF;
  IF NOT coalesce(country = ANY (p.coverage), false) THEN
    RAISE EXCEPTION 'partner request: % does not cover %', p.code, country;
  END IF;
  IF NEW.incident_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM incident WHERE id = NEW.incident_id AND tenant_id = NEW.tenant_id
  ) THEN
    RAISE EXCEPTION 'partner request: no such incident';
  END IF;
  IF NEW.person_id IS NOT NULL THEN
    IF NOT EXISTS (SELECT 1 FROM person WHERE id = NEW.person_id AND tenant_id = NEW.tenant_id) THEN
      RAISE EXCEPTION 'partner request: no such person';
    END IF;
    -- AS-08, G-5: never a traveller on a restricted trip that is being prepared, will
    -- happen or is under way. DRAFT counts: a trip is marked restricted only as a draft
    -- (review of Prompt 44, M2). The trips are locked against a concurrent change (L6);
    -- dates in UTC, as trips (Journey plan G-11; review N8).
    PERFORM 1 FROM trip t JOIN trip_traveller tt ON tt.trip_id = t.id
     WHERE tt.person_id = NEW.person_id AND t.tenant_id = NEW.tenant_id AND t.restricted
       AND t.approval_status IN ('DRAFT','PENDING','APPROVED')
       AND t.ends_on >= (now() AT TIME ZONE 'UTC')::date
       FOR SHARE OF t;
    IF FOUND THEN
      RAISE EXCEPTION 'partner request: a restricted traveller cannot be named';
    END IF;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;
CREATE TRIGGER partner_request_guard BEFORE INSERT OR UPDATE ON partner_request
  FOR EACH ROW EXECUTE FUNCTION partner_request_guard();
