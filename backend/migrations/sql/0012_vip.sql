-- Pilot module 12, VIP & Delegation Protection (D-42): PC-35..38, approved by the product
-- owner on 2026-11-01 (PR #91), with the plan's answers (docs/plan-pilot-vip.md, PR #92). Runs
-- as nexira_owner (D-01). RLS and grants: named human sign-off (D-29). Visits are illustrative
-- (D-19). No table has a position of a principal, team or motorcade (AIR-06, §63 Q4); who may
-- see a visit is enforced in the app (VIP-06). Segment risk is worked out on read, not stored.

-- PC-35 · a visit (VIP-01, VIP-04): seeded, then started, completed or cancelled.
CREATE TABLE vip_visit (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenant(id),
  reference       text NOT NULL CHECK (reference ~ '^VV-[0-9]{4}-[0-9]{3,}$'),
  title           text NOT NULL CHECK (length(title) BETWEEN 1 AND 200),
  mission_id      uuid NOT NULL REFERENCES mission(id),
  -- A role, never a name (§63 Q3).
  principal_role  text NOT NULL CHECK (length(principal_role) BETWEEN 1 AND 100),
  starts_on       date NOT NULL,
  ends_on         date NOT NULL,
  trip_id         uuid REFERENCES trip(id),
  status          text NOT NULL DEFAULT 'PLANNED'
                  CHECK (status IN ('PLANNED','LIVE','COMPLETED','CANCELLED')),
  -- Labels and counts only: team lead, advance team, team size, medic, vehicle codes, safe havens.
  detail          jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(detail) = 'object'),
  started_by      uuid REFERENCES app_user(id),
  started_at      timestamptz,
  cancelled_by    uuid REFERENCES app_user(id),
  cancel_reason   text CHECK (length(cancel_reason) BETWEEN 1 AND 500),
  cancelled_at    timestamptz,
  source          text NOT NULL DEFAULT 'Illustrative visit (simulated)'
                  CHECK (length(source) BETWEEN 1 AND 200),
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, reference),
  CHECK (ends_on >= starts_on),
  CHECK ((started_by IS NULL) = (started_at IS NULL)),
  CHECK (status NOT IN ('LIVE','COMPLETED') OR started_by IS NOT NULL),
  CHECK ((status = 'CANCELLED') = (cancelled_by IS NOT NULL)),
  CHECK ((cancelled_by IS NULL) = (cancel_reason IS NULL)),
  CHECK ((cancelled_by IS NULL) = (cancelled_at IS NULL))
);
CREATE INDEX vip_visit_mission_idx ON vip_visit (tenant_id, mission_id);
ALTER TABLE vip_visit ENABLE ROW LEVEL SECURITY;
ALTER TABLE vip_visit FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON vip_visit
  USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());
GRANT SELECT, INSERT ON vip_visit TO nexira_app;
GRANT UPDATE (status, started_by, cancelled_by, cancel_reason) ON vip_visit TO nexira_app;

-- Foreign keys ignore RLS, so every reference's tenant is checked here (the lesson of Prompts 24
-- and 29). BEFORE triggers run before CHECK constraints. A DELETE is refused for every role.
CREATE FUNCTION vip_visit_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'vip visit: visits are kept';
  END IF;
  IF TG_OP = 'INSERT' THEN
    IF NEW.status <> 'PLANNED' OR NEW.started_by IS NOT NULL OR NEW.cancelled_by IS NOT NULL
       OR NEW.cancel_reason IS NOT NULL THEN
      RAISE EXCEPTION 'vip visit: a visit starts planned';
    END IF;
    PERFORM 1 FROM mission m WHERE m.id = NEW.mission_id AND m.tenant_id = NEW.tenant_id;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'vip visit: no such mission';
    END IF;
    IF NEW.trip_id IS NOT NULL THEN
      -- Only a restricted trip: its flights are never tracked or shown (D-33).
      PERFORM 1 FROM trip t WHERE t.id = NEW.trip_id AND t.tenant_id = NEW.tenant_id AND t.restricted;
      IF NOT FOUND THEN
        RAISE EXCEPTION 'vip visit: the trip is a restricted trip of this tenant';
      END IF;
    END IF;
    NEW.started_at := NULL;
    NEW.cancelled_at := NULL;
    NEW.created_at := now();
    NEW.updated_at := now();
    RETURN NEW;
  END IF;

  -- UPDATE
  IF OLD.status IN ('COMPLETED', 'CANCELLED') THEN
    RAISE EXCEPTION 'vip visit: a % visit is final', lower(OLD.status);
  END IF;
  IF (NEW.id, NEW.tenant_id, NEW.reference, NEW.title, NEW.mission_id, NEW.principal_role,
      NEW.starts_on, NEW.ends_on, NEW.trip_id, NEW.detail, NEW.source, NEW.created_at)
     IS DISTINCT FROM
     (OLD.id, OLD.tenant_id, OLD.reference, OLD.title, OLD.mission_id, OLD.principal_role,
      OLD.starts_on, OLD.ends_on, OLD.trip_id, OLD.detail, OLD.source, OLD.created_at) THEN
    RAISE EXCEPTION 'vip visit: what the visit is stays fixed';
  END IF;
  IF NEW.status <> OLD.status
     AND NOT ((OLD.status = 'PLANNED' AND NEW.status IN ('LIVE', 'CANCELLED'))
              OR (OLD.status = 'LIVE' AND NEW.status IN ('COMPLETED', 'CANCELLED'))) THEN
    RAISE EXCEPTION 'vip visit: % cannot become %', OLD.status, NEW.status;
  END IF;
  IF NEW.started_by IS DISTINCT FROM OLD.started_by
     AND NOT (OLD.status = 'PLANNED' AND NEW.status = 'LIVE') THEN
    RAISE EXCEPTION 'vip visit: who started it is set once, on starting';
  END IF;
  IF (NEW.cancelled_by, NEW.cancel_reason) IS DISTINCT FROM (OLD.cancelled_by, OLD.cancel_reason)
     AND NEW.status <> 'CANCELLED' THEN
    RAISE EXCEPTION 'vip visit: a cancellation sets the status';
  END IF;
  IF OLD.status = 'PLANNED' AND NEW.status = 'LIVE' THEN
    PERFORM 1 FROM app_user u WHERE u.id = NEW.started_by AND u.tenant_id = NEW.tenant_id;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'vip visit: started by someone of this tenant';
    END IF;
    NEW.started_at := now();
  ELSE
    NEW.started_at := OLD.started_at;
  END IF;
  IF NEW.status = 'CANCELLED' THEN
    PERFORM 1 FROM app_user u WHERE u.id = NEW.cancelled_by AND u.tenant_id = NEW.tenant_id;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'vip visit: cancelled by someone of this tenant, with a reason';
    END IF;
    NEW.cancelled_at := now();
  ELSE
    NEW.cancelled_at := OLD.cancelled_at;
  END IF;
  NEW.updated_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;
CREATE TRIGGER vip_visit_guard BEFORE INSERT OR UPDATE OR DELETE ON vip_visit
  FOR EACH ROW EXECUTE FUNCTION vip_visit_guard();

-- PC-36 · the programme (VIP-01, VIP-04, VIP-05): status moves while the visit is live; the time
-- and "virtual" change only in the transaction that approves a change (PC-38).
CREATE TABLE vip_segment (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenant(id),
  visit_id        uuid NOT NULL REFERENCES vip_visit(id),
  seq             smallint NOT NULL CHECK (seq BETWEEN 1 AND 50),
  kind            text NOT NULL
                  CHECK (kind IN ('ARRIVAL','MOTORCADE','MEETING','EVENT','SITE_VISIT','DEPARTURE')),
  title           text NOT NULL CHECK (length(title) BETWEEN 1 AND 200),
  venue_name      text NOT NULL CHECK (length(venue_name) BETWEEN 1 AND 150),
  venue_location  geography(Point,4326) NOT NULL,
  starts_at       timestamptz NOT NULL,
  ends_at         timestamptz,
  attendees       integer CHECK (attendees BETWEEN 0 AND 100000),
  virtual         boolean NOT NULL DEFAULT false,
  status          text NOT NULL DEFAULT 'PLANNED'
                  CHECK (status IN ('PLANNED','IN_PROGRESS','COMPLETED')),
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (visit_id, seq),
  CHECK (ends_at IS NULL OR ends_at > starts_at)
);
CREATE INDEX vip_segment_visit_idx ON vip_segment (tenant_id, visit_id);
ALTER TABLE vip_segment ENABLE ROW LEVEL SECURITY;
ALTER TABLE vip_segment FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON vip_segment
  USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());
GRANT SELECT, INSERT ON vip_segment TO nexira_app;
GRANT UPDATE (status, starts_at, ends_at, virtual) ON vip_segment TO nexira_app;


-- PC-38 · a change proposed by one person and decided by another (VIP-05). Created before the
-- segment guard, which reads it.
CREATE TABLE vip_segment_change (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenant(id),
  segment_id      uuid NOT NULL REFERENCES vip_segment(id),
  new_starts_at   timestamptz,
  new_ends_at     timestamptz,
  make_virtual    boolean NOT NULL DEFAULT false,
  reason          text NOT NULL CHECK (length(reason) BETWEEN 1 AND 500),
  proposed_by     uuid NOT NULL REFERENCES app_user(id),
  proposed_at     timestamptz NOT NULL DEFAULT now(),
  status          text NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','APPROVED','REJECTED')),
  decided_by      uuid REFERENCES app_user(id),
  decided_at      timestamptz,
  decision_note   text CHECK (length(decision_note) BETWEEN 1 AND 500),
  -- Either a new time or virtual, not both.
  CHECK (make_virtual <> (new_starts_at IS NOT NULL)),
  CHECK (new_ends_at IS NULL OR (new_starts_at IS NOT NULL AND new_ends_at > new_starts_at)),
  CHECK ((status = 'PENDING') = (decided_by IS NULL)),
  CHECK ((decided_by IS NULL) = (decided_at IS NULL)),
  CHECK (decided_by IS NULL OR decided_by <> proposed_by)
);
-- One pending change per segment.
CREATE UNIQUE INDEX vip_segment_change_pending_uq ON vip_segment_change (segment_id)
  WHERE status = 'PENDING';
ALTER TABLE vip_segment_change ENABLE ROW LEVEL SECURITY;
ALTER TABLE vip_segment_change FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON vip_segment_change
  USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());
GRANT SELECT, INSERT ON vip_segment_change TO nexira_app;
GRANT UPDATE (status, decided_by, decision_note) ON vip_segment_change TO nexira_app;

CREATE FUNCTION vip_segment_guard() RETURNS trigger AS $$
DECLARE
  visit vip_visit%ROWTYPE;
  change vip_segment_change%ROWTYPE;
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'vip segment: the programme is kept';
  END IF;
  -- FOR SHARE: a segment change waits for a concurrent cancellation or completion, then sees it.
  SELECT * INTO visit FROM vip_visit v
   WHERE v.id = NEW.visit_id AND v.tenant_id = NEW.tenant_id FOR SHARE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'vip segment: no such visit';
  END IF;
  IF TG_OP = 'INSERT' THEN
    IF visit.status <> 'PLANNED' THEN
      RAISE EXCEPTION 'vip segment: the programme is set before the visit starts';
    END IF;
    IF NEW.status <> 'PLANNED' THEN
      RAISE EXCEPTION 'vip segment: a segment starts planned';
    END IF;
    NEW.created_at := now();
    NEW.updated_at := now();
    RETURN NEW;
  END IF;

  -- UPDATE
  IF visit.status IN ('COMPLETED', 'CANCELLED') THEN
    RAISE EXCEPTION 'vip segment: the visit is final';
  END IF;
  IF (NEW.id, NEW.tenant_id, NEW.visit_id, NEW.seq, NEW.kind, NEW.title, NEW.venue_name,
      NEW.venue_location, NEW.attendees, NEW.created_at)
     IS DISTINCT FROM
     (OLD.id, OLD.tenant_id, OLD.visit_id, OLD.seq, OLD.kind, OLD.title, OLD.venue_name,
      OLD.venue_location, OLD.attendees, OLD.created_at) THEN
    RAISE EXCEPTION 'vip segment: what the segment is stays fixed';
  END IF;
  IF NEW.status <> OLD.status THEN
    IF visit.status <> 'LIVE' THEN
      RAISE EXCEPTION 'vip segment: the programme moves only while the visit is live';
    END IF;
    IF NOT ((OLD.status = 'PLANNED' AND NEW.status = 'IN_PROGRESS')
            OR (OLD.status = 'IN_PROGRESS' AND NEW.status = 'COMPLETED')) THEN
      RAISE EXCEPTION 'vip segment: % cannot become %', OLD.status, NEW.status;
    END IF;
  END IF;
  IF (NEW.starts_at, NEW.ends_at, NEW.virtual) IS DISTINCT FROM (OLD.starts_at, OLD.ends_at, OLD.virtual) THEN
    IF OLD.status <> 'PLANNED' THEN
      RAISE EXCEPTION 'vip segment: only a planned segment changes';
    END IF;
    -- Only as a change approved in this transaction (VIP-05): two people decided it.
    SELECT * INTO change FROM vip_segment_change c
     WHERE c.segment_id = NEW.id AND c.tenant_id = NEW.tenant_id AND c.status = 'APPROVED'
       AND c.decided_at = now();
    IF NOT FOUND THEN
      RAISE EXCEPTION 'vip segment: the time or virtual changes only with an approved change';
    END IF;
    IF change.make_virtual THEN
      IF NOT NEW.virtual OR (NEW.starts_at, NEW.ends_at) IS DISTINCT FROM (OLD.starts_at, OLD.ends_at) THEN
        RAISE EXCEPTION 'vip segment: the approved change makes it virtual, nothing else';
      END IF;
    ELSIF NEW.virtual IS DISTINCT FROM OLD.virtual OR NEW.starts_at IS DISTINCT FROM change.new_starts_at
          OR NEW.ends_at IS DISTINCT FROM change.new_ends_at THEN
      RAISE EXCEPTION 'vip segment: the time is the approved change''s';
    END IF;
  END IF;
  NEW.updated_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;
CREATE TRIGGER vip_segment_guard BEFORE INSERT OR UPDATE OR DELETE ON vip_segment
  FOR EACH ROW EXECUTE FUNCTION vip_segment_guard();

CREATE FUNCTION vip_segment_change_guard() RETURNS trigger AS $$
DECLARE
  visit_status text;
  segment_status text;
  segment_virtual boolean;
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'vip change: changes are kept';
  END IF;
  SELECT v.status, s.status, s.virtual INTO visit_status, segment_status, segment_virtual
    FROM vip_segment s JOIN vip_visit v ON v.id = s.visit_id
   WHERE s.id = NEW.segment_id AND s.tenant_id = NEW.tenant_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'vip change: no such segment';
  END IF;
  IF visit_status IN ('COMPLETED', 'CANCELLED') THEN
    RAISE EXCEPTION 'vip change: the visit is final';
  END IF;
  IF TG_OP = 'INSERT' THEN
    IF NEW.status <> 'PENDING' OR NEW.decided_by IS NOT NULL OR NEW.decision_note IS NOT NULL THEN
      RAISE EXCEPTION 'vip change: a change starts pending';
    END IF;
    -- Only a planned segment changes, so a change can always be applied (review of Prompt 78, L3).
    IF segment_status <> 'PLANNED' THEN
      RAISE EXCEPTION 'vip change: only a planned segment changes';
    END IF;
    IF NEW.make_virtual AND segment_virtual THEN
      RAISE EXCEPTION 'vip change: the segment is already virtual';
    END IF;
    PERFORM 1 FROM app_user u WHERE u.id = NEW.proposed_by AND u.tenant_id = NEW.tenant_id;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'vip change: proposed by someone of this tenant';
    END IF;
    NEW.proposed_at := now();
    NEW.decided_at := NULL;
    RETURN NEW;
  END IF;

  -- UPDATE: decided once, by another person.
  IF (NEW.id, NEW.tenant_id, NEW.segment_id, NEW.new_starts_at, NEW.new_ends_at, NEW.make_virtual,
      NEW.reason, NEW.proposed_by, NEW.proposed_at)
     IS DISTINCT FROM
     (OLD.id, OLD.tenant_id, OLD.segment_id, OLD.new_starts_at, OLD.new_ends_at, OLD.make_virtual,
      OLD.reason, OLD.proposed_by, OLD.proposed_at) THEN
    RAISE EXCEPTION 'vip change: what was proposed stays fixed';
  END IF;
  IF OLD.status <> 'PENDING' THEN
    RAISE EXCEPTION 'vip change: a decision is final';
  END IF;
  IF NEW.status NOT IN ('APPROVED', 'REJECTED') OR NEW.decided_by IS NULL THEN
    RAISE EXCEPTION 'vip change: the only change is a decision, by someone';
  END IF;
  IF NEW.decided_by = OLD.proposed_by THEN
    RAISE EXCEPTION 'vip change: the proposer cannot decide (D-05)';
  END IF;
  PERFORM 1 FROM app_user u WHERE u.id = NEW.decided_by AND u.tenant_id = NEW.tenant_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'vip change: decided by someone of this tenant';
  END IF;
  -- One approval per segment per transaction, so the segment guard's "approved in this
  -- transaction" names exactly one change (review of Prompt 78, M2).
  IF NEW.status = 'APPROVED' THEN
    PERFORM 1 FROM vip_segment_change c
     WHERE c.segment_id = NEW.segment_id AND c.id <> NEW.id AND c.status = 'APPROVED'
       AND c.decided_at = now();
    IF FOUND THEN
      RAISE EXCEPTION 'vip change: one approved change per segment at a time';
    END IF;
  END IF;
  NEW.decided_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;
CREATE TRIGGER vip_segment_change_guard BEFORE INSERT OR UPDATE OR DELETE ON vip_segment_change
  FOR EACH ROW EXECUTE FUNCTION vip_segment_change_guard();

-- PC-37 · the pre-visit checklist (VIP-03): each item done once, by a person of the tenant.
CREATE TABLE vip_checklist_item (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   uuid NOT NULL REFERENCES tenant(id),
  visit_id    uuid NOT NULL REFERENCES vip_visit(id),
  label       text NOT NULL CHECK (length(label) BETWEEN 1 AND 200),
  due_on      date NOT NULL,
  done_by     uuid REFERENCES app_user(id),
  done_at     timestamptz,
  created_at  timestamptz NOT NULL DEFAULT now(),
  CHECK ((done_by IS NULL) = (done_at IS NULL))
);
CREATE INDEX vip_checklist_item_visit_idx ON vip_checklist_item (tenant_id, visit_id);
ALTER TABLE vip_checklist_item ENABLE ROW LEVEL SECURITY;
ALTER TABLE vip_checklist_item FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON vip_checklist_item
  USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());
GRANT SELECT, INSERT ON vip_checklist_item TO nexira_app;
GRANT UPDATE (done_by) ON vip_checklist_item TO nexira_app;

CREATE FUNCTION vip_checklist_item_guard() RETURNS trigger AS $$
DECLARE
  visit_status text;
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'vip checklist: items are kept';
  END IF;
  SELECT v.status INTO visit_status FROM vip_visit v
   WHERE v.id = NEW.visit_id AND v.tenant_id = NEW.tenant_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'vip checklist: no such visit';
  END IF;
  IF TG_OP = 'UPDATE' THEN
    IF (NEW.id, NEW.tenant_id, NEW.visit_id, NEW.label, NEW.due_on, NEW.created_at)
       IS DISTINCT FROM (OLD.id, OLD.tenant_id, OLD.visit_id, OLD.label, OLD.due_on, OLD.created_at) THEN
      RAISE EXCEPTION 'vip checklist: the item stays fixed';
    END IF;
    IF OLD.done_by IS NOT NULL THEN
      RAISE EXCEPTION 'vip checklist: done is final';
    END IF;
    IF NEW.done_by IS NULL THEN
      RAISE EXCEPTION 'vip checklist: the only change is marking it done, by someone';
    END IF;
    IF visit_status IN ('COMPLETED', 'CANCELLED') THEN
      RAISE EXCEPTION 'vip checklist: the visit is final';
    END IF;
  ELSE
    IF visit_status IN ('COMPLETED', 'CANCELLED') THEN
      RAISE EXCEPTION 'vip checklist: the visit is final';  -- review of Prompt 78, M1
    END IF;
    NEW.created_at := now();
  END IF;
  -- An item may be seeded already done (plan-pilot-vip G-7); either way by a user of the tenant.
  IF NEW.done_by IS NOT NULL THEN
    PERFORM 1 FROM app_user u WHERE u.id = NEW.done_by AND u.tenant_id = NEW.tenant_id;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'vip checklist: done by someone of this tenant';
    END IF;
    NEW.done_at := now();
  ELSE
    NEW.done_at := NULL;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;
CREATE TRIGGER vip_checklist_item_guard BEFORE INSERT OR UPDATE OR DELETE ON vip_checklist_item
  FOR EACH ROW EXECUTE FUNCTION vip_checklist_item_guard();
