-- Pilot module 17, After-Action Review (D-47): PC-49 and PC-50, approved by the product owner on
-- 2026-11-09 (PR #134), with the plan's answers (docs/plan-pilot-aar.md, PR #135). Runs as
-- nexira_owner (D-01). RLS and grants: named human sign-off (D-29). The timeline and the draft
-- metrics are worked out on read; only the review, its frozen metrics and the items are stored.

-- PC-49 · one review per incident (AAR-01, AAR-06): DRAFT, then FINAL once, with the metrics
-- frozen. The reference is written by the database from the incident's (INC-2026-1042 →
-- AAR-2026-1042).
CREATE TABLE after_action_review (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL REFERENCES tenant(id),
  incident_id   uuid NOT NULL UNIQUE REFERENCES incident(id),
  reference     text NOT NULL CHECK (reference ~ '^AAR-'),
  status        text NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT','FINAL')),
  metrics       jsonb CHECK (jsonb_typeof(metrics) = 'object'),
  started_by    uuid NOT NULL REFERENCES app_user(id),
  started_at    timestamptz NOT NULL DEFAULT now(),
  finalised_by  uuid REFERENCES app_user(id),
  finalised_at  timestamptz,
  UNIQUE (tenant_id, reference),
  CHECK ((status = 'FINAL') = (metrics IS NOT NULL)),
  CHECK ((status = 'FINAL') = (finalised_by IS NOT NULL))
);
ALTER TABLE after_action_review ENABLE ROW LEVEL SECURITY;
ALTER TABLE after_action_review FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON after_action_review
  USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());
GRANT SELECT, INSERT ON after_action_review TO nexira_app;
GRANT UPDATE (status, metrics, finalised_by) ON after_action_review TO nexira_app;

-- Foreign keys ignore RLS, so every reference's tenant is checked here (the lesson of Prompts 24
-- and 29). A review starts only once its incident is no longer ACTIVE (§88 Q2), and is finalised
-- only when no item is still a draft (AAR-06). A DELETE is refused for every role.
CREATE FUNCTION aar_review_guard() RETURNS trigger AS $$
DECLARE
  incident_ref text;
  incident_status text;
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'after-action review: the review is kept';
  END IF;
  IF TG_OP = 'UPDATE' THEN
    IF (NEW.id, NEW.tenant_id, NEW.incident_id, NEW.reference, NEW.started_by, NEW.started_at)
       IS DISTINCT FROM
       (OLD.id, OLD.tenant_id, OLD.incident_id, OLD.reference, OLD.started_by, OLD.started_at) THEN
      RAISE EXCEPTION 'after-action review: only finalising changes it';
    END IF;
    IF OLD.status <> 'DRAFT' OR NEW.status <> 'FINAL' THEN
      RAISE EXCEPTION 'after-action review: a review is finalised once';
    END IF;
    PERFORM 1 FROM app_user u WHERE u.id = NEW.finalised_by AND u.tenant_id = NEW.tenant_id;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'after-action review: no such user';
    END IF;
    PERFORM 1 FROM aar_item i WHERE i.review_id = NEW.id AND i.status = 'DRAFT';
    IF FOUND THEN
      RAISE EXCEPTION 'after-action review: drafts are still to be decided';
    END IF;
    NEW.finalised_at := now();
    RETURN NEW;
  END IF;
  SELECT i.reference, i.status INTO incident_ref, incident_status
    FROM incident i WHERE i.id = NEW.incident_id AND i.tenant_id = NEW.tenant_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'after-action review: no such incident';
  END IF;
  IF incident_status NOT IN ('MONITORING','CLOSED') THEN
    RAISE EXCEPTION 'after-action review: the incident is still active';
  END IF;
  PERFORM 1 FROM app_user u WHERE u.id = NEW.started_by AND u.tenant_id = NEW.tenant_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'after-action review: no such user';
  END IF;
  IF NEW.status <> 'DRAFT' OR NEW.metrics IS NOT NULL OR NEW.finalised_by IS NOT NULL THEN
    RAISE EXCEPTION 'after-action review: a review starts as a draft';
  END IF;
  NEW.reference := 'AAR' || substr(incident_ref, 4);
  NEW.started_at := now();
  NEW.finalised_at := NULL;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;
CREATE TRIGGER aar_review_guard BEFORE INSERT OR UPDATE OR DELETE ON after_action_review
  FOR EACH ROW EXECUTE FUNCTION aar_review_guard();

-- PC-50 · the lessons and actions (AAR-04, AAR-05): a rule's draft, decided by a person, or a
-- reviewer's own (accepted when added). DRAFT → ACCEPTED or REJECTED, ACCEPTED → DONE; on a
-- FINAL review only ACCEPTED → DONE.
CREATE TABLE aar_item (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    uuid NOT NULL REFERENCES tenant(id),
  review_id    uuid NOT NULL REFERENCES after_action_review(id),
  rule_code    text CHECK (rule_code ~ '^[A-Z][A-Z_]{2,39}$'),
  finding      text NOT NULL CHECK (length(finding) BETWEEN 1 AND 500),
  action       text NOT NULL CHECK (length(action) BETWEEN 1 AND 500),
  owner_team   text NOT NULL CHECK (owner_team IN ('SECURITY','HR','FACILITIES','FLEET','CONSULAR',
                 'LOGISTICS','COMMUNICATIONS','IT','MISSION_MANAGEMENT')),
  priority     text NOT NULL CHECK (priority IN ('HIGH','MEDIUM','LOW')),
  evidence     jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(evidence) = 'object'),
  status       text NOT NULL DEFAULT 'DRAFT'
               CHECK (status IN ('DRAFT','ACCEPTED','REJECTED','DONE')),
  due_on       date,
  reason       text CHECK (length(reason) BETWEEN 1 AND 500),
  decided_by   uuid REFERENCES app_user(id),
  decided_at   timestamptz,
  done_by      uuid REFERENCES app_user(id),
  done_at      timestamptz,
  created_at   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (review_id, rule_code),
  CHECK ((status = 'DRAFT') = (decided_by IS NULL)),
  CHECK ((status = 'REJECTED') = (reason IS NOT NULL)),
  CHECK (status NOT IN ('ACCEPTED','DONE') OR due_on IS NOT NULL),
  CHECK ((status = 'DONE') = (done_by IS NOT NULL))
);
CREATE INDEX aar_item_review_idx ON aar_item (review_id);
ALTER TABLE aar_item ENABLE ROW LEVEL SECURITY;
ALTER TABLE aar_item FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON aar_item
  USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());
GRANT SELECT, INSERT ON aar_item TO nexira_app;
GRANT UPDATE (finding, action, owner_team, priority, due_on, status, reason, decided_by, done_by)
  ON aar_item TO nexira_app;

CREATE FUNCTION aar_item_guard() RETURNS trigger AS $$
DECLARE
  review_status text;
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'aar item: the item is kept';
  END IF;
  -- Locks the review against a finalise running at the same time (AAR-06).
  SELECT r.status INTO review_status FROM after_action_review r
   WHERE r.id = NEW.review_id AND r.tenant_id = NEW.tenant_id FOR SHARE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'aar item: no such review';
  END IF;
  IF TG_OP = 'INSERT' THEN
    IF review_status <> 'DRAFT' THEN
      RAISE EXCEPTION 'aar item: the review is final';
    END IF;
    IF NEW.done_by IS NOT NULL THEN
      RAISE EXCEPTION 'aar item: an item is done only once accepted';
    END IF;
    -- A rule's draft waits for a person; a reviewer's own is accepted when added.
    IF NEW.rule_code IS NOT NULL AND NEW.status <> 'DRAFT' THEN
      RAISE EXCEPTION 'aar item: a rule''s item starts as a draft';
    END IF;
    IF NEW.rule_code IS NULL AND NEW.status <> 'ACCEPTED' THEN
      RAISE EXCEPTION 'aar item: a reviewer''s own item is accepted';
    END IF;
    IF NEW.decided_by IS NOT NULL THEN
      PERFORM 1 FROM app_user u WHERE u.id = NEW.decided_by AND u.tenant_id = NEW.tenant_id;
      IF NOT FOUND THEN
        RAISE EXCEPTION 'aar item: no such user';
      END IF;
      NEW.decided_at := now();
    ELSE
      NEW.decided_at := NULL;
    END IF;
    NEW.done_at := NULL;
    NEW.created_at := now();
    RETURN NEW;
  END IF;
  IF (NEW.id, NEW.tenant_id, NEW.review_id, NEW.rule_code, NEW.evidence, NEW.created_at)
     IS DISTINCT FROM (OLD.id, OLD.tenant_id, OLD.review_id, OLD.rule_code, OLD.evidence,
                       OLD.created_at) THEN
    RAISE EXCEPTION 'aar item: the review, rule and evidence are fixed';
  END IF;
  IF OLD.status = 'DRAFT' AND NEW.status IN ('ACCEPTED','REJECTED') THEN
    IF review_status <> 'DRAFT' THEN
      RAISE EXCEPTION 'aar item: the review is final';
    END IF;
    PERFORM 1 FROM app_user u WHERE u.id = NEW.decided_by AND u.tenant_id = NEW.tenant_id;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'aar item: no such user';
    END IF;
    IF NEW.done_by IS NOT NULL THEN
      RAISE EXCEPTION 'aar item: an item is done only once accepted';
    END IF;
    NEW.decided_at := now();
    NEW.done_at := NULL;
    RETURN NEW;
  END IF;
  IF OLD.status = 'ACCEPTED' AND NEW.status = 'DONE' THEN
    -- Marking done changes nothing else, on a draft or a final review.
    IF (NEW.finding, NEW.action, NEW.owner_team, NEW.priority, NEW.due_on, NEW.reason,
        NEW.decided_by, NEW.decided_at)
       IS DISTINCT FROM (OLD.finding, OLD.action, OLD.owner_team, OLD.priority, OLD.due_on,
                         OLD.reason, OLD.decided_by, OLD.decided_at) THEN
      RAISE EXCEPTION 'aar item: marking done changes nothing else';
    END IF;
    PERFORM 1 FROM app_user u WHERE u.id = NEW.done_by AND u.tenant_id = NEW.tenant_id;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'aar item: no such user';
    END IF;
    NEW.done_at := now();
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'aar item: DRAFT → ACCEPTED or REJECTED, ACCEPTED → DONE only';
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;
CREATE TRIGGER aar_item_guard BEFORE INSERT OR UPDATE OR DELETE ON aar_item
  FOR EACH ROW EXECUTE FUNCTION aar_item_guard();
