-- Pilot module 7, Document Expiry (D-37): PC-23, approved by the product owner on
-- 2026-10-30 (PR #57), with the plan's answers (docs/plan-pilot-dx.md, PR #58; G-1 amends
-- the grants). Runs as nexira_owner (D-01). RLS and grants: named human sign-off (D-29).

-- PC-23 · travel and status documents of staff and dependants (DX-01, DX-04). Simulated
-- (D-19). Never a document number, scan or photo (D-37). No DELETE.
CREATE TABLE travel_document (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id             uuid NOT NULL REFERENCES tenant(id),
  person_id             uuid NOT NULL REFERENCES person(id),
  doc_type              text NOT NULL CHECK (doc_type IN (
                          'PASSPORT','DIPLOMATIC_PASSPORT','VISA','RESIDENCE_PERMIT',
                          'ACCREDITATION','SECURITY_CLEARANCE')),
  issuing_country       char(2) NOT NULL CHECK (issuing_country ~ '^[A-Z]{2}$'),
  -- A real date: never 'infinity', which would never expire nor renew (review of Prompt 49, M3).
  valid_until           date NOT NULL CHECK (valid_until BETWEEN DATE '1900-01-01' AND DATE '2200-12-31'),
  renewal_status        text NOT NULL DEFAULT 'NONE'
                        CHECK (renewal_status IN ('NONE','REQUESTED','IN_PROGRESS','RENEWED')),
  -- Who did each renewal step: a user id, or the system actor (plan G-1). The app writes
  -- who; the trigger writes when.
  renewal_requested_by  text CHECK (length(renewal_requested_by) BETWEEN 1 AND 100),
  renewal_requested_at  timestamptz,
  renewal_started_by    text CHECK (length(renewal_started_by) BETWEEN 1 AND 100),
  renewal_started_at    timestamptz,
  renewed_by            text CHECK (length(renewed_by) BETWEEN 1 AND 100),
  renewed_at            timestamptz,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now(),
  CHECK ((renewal_requested_by IS NULL) = (renewal_requested_at IS NULL)),
  CHECK ((renewal_started_by IS NULL) = (renewal_started_at IS NULL)),
  CHECK ((renewed_by IS NULL) = (renewed_at IS NULL)),
  -- Each status has exactly the steps that lead to it (NONE -> IN_PROGRESS skips REQUESTED).
  CHECK (CASE renewal_status
           WHEN 'NONE' THEN renewal_requested_at IS NULL AND renewal_started_at IS NULL
           WHEN 'REQUESTED' THEN renewal_requested_at IS NOT NULL AND renewal_started_at IS NULL
           ELSE renewal_started_at IS NOT NULL
         END),
  CHECK ((renewal_status = 'RENEWED') = (renewed_at IS NOT NULL))
);
CREATE INDEX travel_document_valid_idx ON travel_document (tenant_id, valid_until);
CREATE INDEX travel_document_person_idx ON travel_document (tenant_id, person_id);
ALTER TABLE travel_document ENABLE ROW LEVEL SECURITY;
ALTER TABLE travel_document FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON travel_document
  USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());
-- Only the renewal moves (plan G-1): its status, the new date and who did each step.
GRANT SELECT, INSERT ON travel_document TO nexira_app;
GRANT UPDATE (renewal_status, valid_until, renewal_requested_by, renewal_started_by, renewed_by)
  ON travel_document TO nexira_app;

-- The document rules (plan-pilot-dx.md §6, G-1). Foreign keys ignore RLS, so the holder's
-- tenant is checked here (the lesson of Prompts 24 and 29). The trigger runs as the
-- caller; the tenant_id condition keeps the rule true for a role that bypasses RLS.
-- search_path pinned, pg_temp last (the lesson of Prompt 39).
CREATE FUNCTION travel_document_guard() RETURNS trigger AS $$
DECLARE
  holder  text;
BEGIN
  IF TG_OP = 'UPDATE' THEN
    -- The document itself is fixed; only its renewal moves.
    IF (NEW.id, NEW.tenant_id, NEW.person_id, NEW.doc_type, NEW.issuing_country, NEW.created_at)
       IS DISTINCT FROM
       (OLD.id, OLD.tenant_id, OLD.person_id, OLD.doc_type, OLD.issuing_country, OLD.created_at) THEN
      RAISE EXCEPTION 'travel document: the document itself is fixed';
    END IF;
    IF (NEW.renewal_requested_at, NEW.renewal_started_at, NEW.renewed_at)
       IS DISTINCT FROM (OLD.renewal_requested_at, OLD.renewal_started_at, OLD.renewed_at) THEN
      RAISE EXCEPTION 'travel document: renewal times are written by the database';
    END IF;
    IF NEW.renewal_status IS DISTINCT FROM OLD.renewal_status THEN
      IF NOT (
        (OLD.renewal_status = 'NONE' AND NEW.renewal_status IN ('REQUESTED','IN_PROGRESS'))
        OR (OLD.renewal_status = 'REQUESTED' AND NEW.renewal_status = 'IN_PROGRESS')
        OR (OLD.renewal_status = 'IN_PROGRESS' AND NEW.renewal_status = 'RENEWED')
      ) THEN
        RAISE EXCEPTION 'travel document: renewal % cannot become %',
          OLD.renewal_status, NEW.renewal_status;
      END IF;
    END IF;
    -- Who did a step is written on that step, and only then (plan G-1).
    IF NEW.renewal_requested_by IS DISTINCT FROM OLD.renewal_requested_by
       AND NOT (OLD.renewal_status = 'NONE' AND NEW.renewal_status = 'REQUESTED') THEN
      RAISE EXCEPTION 'travel document: who requested is recorded only on that step';
    END IF;
    IF NEW.renewal_started_by IS DISTINCT FROM OLD.renewal_started_by
       AND NOT (OLD.renewal_status IN ('NONE','REQUESTED') AND NEW.renewal_status = 'IN_PROGRESS') THEN
      RAISE EXCEPTION 'travel document: who started is recorded only on that step';
    END IF;
    IF NEW.renewed_by IS DISTINCT FROM OLD.renewed_by
       AND NOT (OLD.renewal_status = 'IN_PROGRESS' AND NEW.renewal_status = 'RENEWED') THEN
      RAISE EXCEPTION 'travel document: who renewed is recorded only on that step';
    END IF;
    -- A new date only when renewed, and always a later one.
    IF NEW.valid_until IS DISTINCT FROM OLD.valid_until
       AND NOT (OLD.renewal_status = 'IN_PROGRESS' AND NEW.renewal_status = 'RENEWED') THEN
      RAISE EXCEPTION 'travel document: the date changes only when renewed';
    END IF;
    IF NEW.renewal_status IS DISTINCT FROM OLD.renewal_status THEN
      IF NEW.renewal_status = 'REQUESTED' THEN
        IF NEW.renewal_requested_by IS NULL THEN
          RAISE EXCEPTION 'travel document: say who requested the renewal';
        END IF;
        NEW.renewal_requested_at := now();
      ELSIF NEW.renewal_status = 'IN_PROGRESS' THEN
        IF NEW.renewal_started_by IS NULL THEN
          RAISE EXCEPTION 'travel document: say who started the renewal';
        END IF;
        NEW.renewal_started_at := now();
      ELSE  -- RENEWED
        IF NEW.renewed_by IS NULL THEN
          RAISE EXCEPTION 'travel document: say who renewed it';
        END IF;
        IF NOT NEW.valid_until > OLD.valid_until THEN
          RAISE EXCEPTION 'travel document: a renewed document is valid until a later date';
        END IF;
        NEW.renewed_at := now();
      END IF;
    END IF;
    NEW.updated_at := now();
    RETURN NEW;
  END IF;

  -- INSERT: a document of a staff member or dependant in its own tenant, not in renewal.
  IF NEW.renewal_status <> 'NONE'
     OR (NEW.renewal_requested_by, NEW.renewal_requested_at, NEW.renewal_started_by,
         NEW.renewal_started_at, NEW.renewed_by, NEW.renewed_at) IS DISTINCT FROM
        (NULL::text, NULL::timestamptz, NULL::text, NULL::timestamptz, NULL::text,
         NULL::timestamptz) THEN
    RAISE EXCEPTION 'travel document: a document starts with no renewal';
  END IF;
  -- Locked, so the holder's type cannot change while the document is added (review L10).
  SELECT p.person_type INTO holder FROM person p
   WHERE p.id = NEW.person_id AND p.tenant_id = NEW.tenant_id
     FOR SHARE OF p;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'travel document: no such person';
  END IF;
  IF holder NOT IN ('DIPLOMAT','LOCAL_STAFF','DEPENDANT','CONTRACTOR') THEN
    RAISE EXCEPTION 'travel document: a % has no documents here', holder;
  END IF;
  NEW.created_at := now();
  NEW.updated_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;
CREATE TRIGGER travel_document_guard BEFORE INSERT OR UPDATE ON travel_document
  FOR EACH ROW EXECUTE FUNCTION travel_document_guard();
