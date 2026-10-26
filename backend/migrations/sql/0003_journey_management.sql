-- Pilot module 2, Journey Management (D-32): PC-14, PC-15 and PC-16, approved by the
-- product owner on 2026-10-26 (PR #24), with the plan's answers (docs/plan-pilot-jrn.md,
-- PR #25). Runs as nexira_owner (D-01). RLS and grants: named human sign-off (D-29).

-- PC-16 · simulated base risk per country (D-19: shown as simulated).
CREATE TABLE country_risk (
  tenant_id     uuid NOT NULL REFERENCES tenant(id),
  country_code  char(2) NOT NULL,
  level         text NOT NULL CHECK (level IN ('LOW','MODERATE','HIGH','CRITICAL')),
  security      smallint NOT NULL CHECK (security BETWEEN 0 AND 100),
  unrest        smallint NOT NULL CHECK (unrest BETWEEN 0 AND 100),
  health        smallint NOT NULL CHECK (health BETWEEN 0 AND 100),
  transport     smallint NOT NULL CHECK (transport BETWEEN 0 AND 100),
  source        text NOT NULL,               -- e.g. "Riskline (simulated)"
  updated_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, country_code)
);
ALTER TABLE country_risk ENABLE ROW LEVEL SECURITY;
ALTER TABLE country_risk FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON country_risk
  USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());
-- INSERT for the seed, which loads through the service layer as nexira_api (plan Q10);
-- not edited in the pilot, so no UPDATE or DELETE.
GRANT SELECT, INSERT ON country_risk TO nexira_app;

-- PC-14 · the itinerary.
CREATE TABLE trip_segment (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    uuid NOT NULL REFERENCES tenant(id),
  trip_id      uuid NOT NULL REFERENCES trip(id) ON DELETE CASCADE,
  seq          smallint NOT NULL CHECK (seq > 0),
  kind         text NOT NULL CHECK (kind IN ('FLIGHT','STAY','MEETING','GROUND')),
  title        text NOT NULL,
  place_label  text,
  location     geography(Point,4326),
  starts_at    timestamptz NOT NULL,
  ends_at      timestamptz NOT NULL,
  CHECK (ends_at >= starts_at),
  UNIQUE (trip_id, seq)
);
ALTER TABLE trip_segment ENABLE ROW LEVEL SECURITY;
ALTER TABLE trip_segment FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON trip_segment
  USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());
GRANT SELECT, INSERT, UPDATE, DELETE ON trip_segment TO nexira_app;  -- while DRAFT (trigger)

-- PC-15 · trip approval and checklist.
ALTER TABLE trip DROP CONSTRAINT trip_approval_status_check;
ALTER TABLE trip ADD CONSTRAINT trip_approval_status_check
  CHECK (approval_status IN ('DRAFT','PENDING','APPROVED','REJECTED','CANCELLED'));
ALTER TABLE trip ALTER COLUMN approval_status SET DEFAULT 'DRAFT';
ALTER TABLE trip
  ADD COLUMN mission_id          uuid REFERENCES mission(id),     -- approval scope (plan G-2)
  ADD COLUMN requested_by        uuid REFERENCES app_user(id),    -- NULL: seeded/system trip
  ADD COLUMN submitted_at        timestamptz,
  ADD COLUMN approved_by         uuid REFERENCES app_user(id),    -- NULL: LOW, auto-approved
  ADD COLUMN approved_at         timestamptz,
  ADD COLUMN approved_risk_level text CHECK (approved_risk_level IN ('LOW','MODERATE','HIGH','CRITICAL')),
  ADD COLUMN rejection_reason    text,
  ADD COLUMN checklist           jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(checklist) = 'object');

-- Plan G-4: trips approved or pending before this migration (the seeded TRP-8812) keep
-- their state. FORCE RLS hides every row from the owner without a tenant, so it is
-- lifted for these statements, inside this transaction.
ALTER TABLE trip NO FORCE ROW LEVEL SECURITY;
UPDATE trip SET submitted_at = created_at WHERE approval_status IN ('PENDING','APPROVED');
UPDATE trip SET approved_at = created_at, approved_risk_level = risk_level
 WHERE approval_status = 'APPROVED';
ALTER TABLE trip FORCE ROW LEVEL SECURITY;

ALTER TABLE trip ADD CONSTRAINT trip_approved_check
  CHECK (approval_status <> 'APPROVED'
         OR (approved_at IS NOT NULL AND approved_risk_level IS NOT NULL));
ALTER TABLE trip ADD CONSTRAINT trip_approver_check
  CHECK (approved_by IS NULL OR approved_at IS NOT NULL);
-- Only an approved trip (or one cancelled after approval) carries an approval.
ALTER TABLE trip ADD CONSTRAINT trip_approval_only_check
  CHECK (approval_status IN ('APPROVED','CANCELLED')
         OR (approved_at IS NULL AND approved_by IS NULL AND approved_risk_level IS NULL));
ALTER TABLE trip ADD CONSTRAINT trip_submitted_check
  CHECK (approval_status NOT IN ('PENDING','APPROVED') OR submitted_at IS NOT NULL);

-- The database backstop for D-32, as PC-10..12 are for campaigns. A user's trip
-- (requested_by set) starts as a DRAFT; seeded trips (requested_by NULL) may be loaded
-- in any state but never with an approver. The database records when a trip was
-- created, submitted and approved; the app never writes those times.
CREATE FUNCTION trip_guard() RETURNS trigger AS $$
DECLARE
  levels constant text[] := ARRAY['LOW','MODERATE','HIGH','CRITICAL'];
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NEW.approved_by IS NOT NULL OR NEW.approved_at IS NOT NULL
       OR NEW.approved_risk_level IS NOT NULL THEN
      RAISE EXCEPTION 'trip: a trip cannot be created with an approval';
    END IF;
    IF NEW.submitted_at IS NOT NULL OR NEW.rejection_reason IS NOT NULL THEN
      RAISE EXCEPTION 'trip: a trip cannot be created as submitted or rejected';
    END IF;
    IF NEW.requested_by IS NOT NULL AND NEW.approval_status <> 'DRAFT' THEN
      RAISE EXCEPTION 'trip: a trip starts as a DRAFT';
    END IF;
    -- trip_child_guard reads it: a seeded trip takes its travellers in this transaction.
    NEW.created_at := now();
    IF NEW.approval_status IN ('PENDING','APPROVED') THEN  -- a seeded trip
      NEW.submitted_at := now();
    END IF;
    IF NEW.approval_status = 'APPROVED' THEN
      NEW.approved_at := now();
      NEW.approved_risk_level := NEW.risk_level;
    END IF;
    RETURN NEW;
  END IF;

  IF NEW.reference IS DISTINCT FROM OLD.reference
     OR NEW.created_at IS DISTINCT FROM OLD.created_at
     OR NEW.requested_by IS DISTINCT FROM OLD.requested_by THEN
    RAISE EXCEPTION 'trip: reference, created_at and requested_by cannot change';
  END IF;
  -- What is approved is what travels: frozen once submitted.
  IF OLD.approval_status <> 'DRAFT' AND (
       NEW.purpose IS DISTINCT FROM OLD.purpose
       OR NEW.origin IS DISTINCT FROM OLD.origin
       OR NEW.destination IS DISTINCT FROM OLD.destination
       OR NEW.destination_country IS DISTINCT FROM OLD.destination_country
       OR NEW.starts_on IS DISTINCT FROM OLD.starts_on
       OR NEW.ends_on IS DISTINCT FROM OLD.ends_on
       OR NEW.risk_level IS DISTINCT FROM OLD.risk_level
       OR NEW.mission_id IS DISTINCT FROM OLD.mission_id) THEN
    RAISE EXCEPTION 'trip: the trip is frozen once it leaves DRAFT';
  END IF;
  IF OLD.approval_status IN ('APPROVED','CANCELLED','REJECTED')
     AND NEW.checklist IS DISTINCT FROM OLD.checklist THEN
    RAISE EXCEPTION 'trip: the checklist is closed once the trip is %', OLD.approval_status;
  END IF;
  IF NEW.approval_status IS DISTINCT FROM OLD.approval_status AND NOT (
       (OLD.approval_status = 'DRAFT' AND NEW.approval_status IN ('PENDING','APPROVED','CANCELLED'))
       OR (OLD.approval_status = 'PENDING' AND NEW.approval_status IN ('DRAFT','APPROVED','CANCELLED'))
       OR (OLD.approval_status = 'APPROVED' AND NEW.approval_status = 'CANCELLED')) THEN
    RAISE EXCEPTION 'trip: status cannot go from % to %', OLD.approval_status, NEW.approval_status;
  END IF;
  IF NEW.rejection_reason IS DISTINCT FROM OLD.rejection_reason
     AND NOT (OLD.approval_status = 'PENDING' AND NEW.approval_status = 'DRAFT') THEN
    RAISE EXCEPTION 'trip: a rejection reason is written only on rejection';
  END IF;
  IF OLD.approval_status = 'DRAFT' AND NEW.approval_status IN ('PENDING','APPROVED') THEN
    NEW.submitted_at := now();
  ELSIF NEW.submitted_at IS DISTINCT FROM OLD.submitted_at THEN
    RAISE EXCEPTION 'trip: submitted_at is recorded only on submission';
  END IF;
  -- An approval is written only by the step that approves, and never rewritten.
  IF NEW.approval_status = 'APPROVED' AND OLD.approval_status <> 'APPROVED' THEN
    IF NEW.approved_risk_level IS NULL THEN
      RAISE EXCEPTION 'trip: an approval records the risk level approved';
    END IF;
    IF NEW.approved_by IS NULL THEN
      -- Only a LOW trip is approved on submission with no second person (D-32, plan G-6).
      IF NOT (OLD.approval_status = 'DRAFT' AND NEW.risk_level = 'LOW'
              AND NEW.approved_risk_level = 'LOW') THEN
        RAISE EXCEPTION 'trip: only a LOW trip is approved without an approver';
      END IF;
    ELSE
      IF OLD.approval_status <> 'PENDING' THEN
        RAISE EXCEPTION 'trip: only a pending trip is approved by a second person';
      END IF;
      IF NEW.approved_by = NEW.requested_by THEN
        RAISE EXCEPTION 'trip: the requester cannot approve their own trip (D-32)';
      END IF;
      -- Plan G-7: the level approved is the live one, never below what was submitted.
      IF array_position(levels, NEW.approved_risk_level) < array_position(levels, NEW.risk_level) THEN
        RAISE EXCEPTION 'trip: an approval cannot record a lower risk than was submitted';
      END IF;
    END IF;
    NEW.approved_at := now();
  ELSIF NEW.approved_at IS DISTINCT FROM OLD.approved_at
        OR NEW.approved_by IS DISTINCT FROM OLD.approved_by
        OR NEW.approved_risk_level IS DISTINCT FROM OLD.approved_risk_level THEN
    IF OLD.approved_at IS NOT NULL THEN
      RAISE EXCEPTION 'trip: an approval cannot change once recorded';
    END IF;
    RAISE EXCEPTION 'trip: an approval is recorded only by approving';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER trip_guard BEFORE INSERT OR UPDATE ON trip
  FOR EACH ROW EXECUTE FUNCTION trip_guard();

-- Travellers and segments change only while their trip is a DRAFT, except that a seeded
-- trip (requested_by NULL) takes its travellers in the transaction that inserted it
-- (plan G-4; trip_guard sets created_at to now(), the transaction's start). The trip
-- row is locked FOR SHARE so a submission or approval waits for this change to commit.
CREATE FUNCTION trip_child_guard() RETURNS trigger AS $$
DECLARE
  t record;
BEGIN
  IF TG_OP = 'UPDATE' AND NEW.trip_id IS DISTINCT FROM OLD.trip_id THEN
    RAISE EXCEPTION 'trip: a traveller or segment cannot move to another trip';
  END IF;
  SELECT approval_status, requested_by, created_at INTO t FROM trip
   WHERE id = CASE WHEN TG_OP = 'DELETE' THEN OLD.trip_id ELSE NEW.trip_id END
     FOR SHARE;
  IF NOT FOUND THEN
    IF TG_OP = 'DELETE' THEN
      RETURN OLD;  -- the owner's cascade from a deleted trip
    END IF;
    RAISE EXCEPTION 'trip: no such trip';  -- includes another tenant's (FKs ignore RLS)
  END IF;
  IF t.approval_status <> 'DRAFT'
     AND NOT (t.requested_by IS NULL AND t.created_at = now()) THEN
    RAISE EXCEPTION 'trip: travellers and itinerary are frozen once the trip leaves DRAFT';
  END IF;
  RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER trip_traveller_guard BEFORE INSERT OR UPDATE OR DELETE ON trip_traveller
  FOR EACH ROW EXECUTE FUNCTION trip_child_guard();
CREATE TRIGGER trip_segment_guard BEFORE INSERT OR UPDATE OR DELETE ON trip_segment
  FOR EACH ROW EXECUTE FUNCTION trip_child_guard();

-- Trips are cancelled, never deleted (travellers go with the draft they belong to).
REVOKE DELETE ON trip FROM nexira_app;
