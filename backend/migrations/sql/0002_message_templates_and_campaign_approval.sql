-- Pilot module 1, Mass Notification (D-31): PC-07 and PC-08, approved by the product
-- owner on 2026-10-25 (PR #16). Runs as nexira_owner (D-01). Changes to RLS or grants
-- need a named human reviewer's sign-off (D-29).

-- PC-07 · message templates per mission and kind, with a generic fallback (mission_id NULL).
CREATE TABLE message_template (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   uuid NOT NULL REFERENCES tenant(id),
  code        text NOT NULL,                       -- e.g. CIVIL_UNREST_SHELTER
  kind        text NOT NULL CHECK (kind IN ('ALERT','ADVISORY','CHECKIN')),
  mission_id  uuid REFERENCES mission(id),         -- NULL = the generic template
  name        text NOT NULL,
  texts       jsonb NOT NULL CHECK (jsonb_typeof(texts) = 'object' AND texts ? 'en'),
  reviewed    jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(reviewed) = 'object'), -- {"fr": true} (D-15)
  is_active   boolean NOT NULL DEFAULT true,       -- deactivated, never deleted
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  -- NULLS NOT DISTINCT: one generic template per code, not one per NULL.
  UNIQUE NULLS NOT DISTINCT (tenant_id, code, mission_id)
);
CREATE TRIGGER message_template_updated BEFORE UPDATE ON message_template
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE message_template ENABLE ROW LEVEL SECURITY;
ALTER TABLE message_template FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON message_template
  USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());
-- No DELETE: a template in use by a campaign is deactivated instead.
GRANT SELECT, INSERT, UPDATE ON message_template TO nexira_app;

-- PC-08 · second-person approval for campaigns that reach citizens (MN-05).
ALTER TABLE notification_campaign DROP CONSTRAINT notification_campaign_status_check;
ALTER TABLE notification_campaign ADD CONSTRAINT notification_campaign_status_check
  CHECK (status IN ('DRAFT','PENDING_APPROVAL','SENDING','SENT','CANCELLED'));
ALTER TABLE notification_campaign
  ADD COLUMN template_id      uuid REFERENCES message_template(id),
  ADD COLUMN submitted_by     uuid REFERENCES app_user(id),
  ADD COLUMN approved_by      uuid REFERENCES app_user(id),
  ADD COLUMN approved_at      timestamptz,
  ADD COLUMN rejection_reason text;

ALTER TABLE notification_campaign ADD CONSTRAINT notification_campaign_submitted_check
  CHECK (status <> 'PENDING_APPROVAL' OR submitted_by IS NOT NULL);  -- PC-10 (5)
ALTER TABLE notification_campaign ADD CONSTRAINT notification_campaign_approved_check
  CHECK ((approved_by IS NULL) = (approved_at IS NULL));  -- PC-11 (3)
ALTER TABLE notification_campaign ADD CONSTRAINT notification_campaign_escalate_check
  CHECK (escalate_after_s > 0);  -- PC-12 (2)

-- Database backstop for D-31 (PC-08, hardened by PC-10 after the review of Prompt 18),
-- as proposal_approval has for D-16:
-- - a campaign is never created approved, and is approved only while PENDING_APPROVAL;
-- - the author and the submitter are frozen, so they cannot be rewritten to get past
--   the check below, and an approval is never rewritten or cleared;
-- - neither the author nor the submitter approves it. The author is compared as a uuid;
--   a user campaign whose author is not a uuid cannot be approved at all (fails closed);
-- - PC-11: what is approved is what is sent. The content is frozen once the campaign
--   leaves DRAFT, approving moves it on to SENDING in the same statement (an approved
--   campaign is never DRAFT or PENDING_APPROVAL), and
--   the approval time is the database's, set when the approval is recorded;
-- - PC-12: the status only moves forward (DRAFT -> PENDING_APPROVAL | SENDING |
--   CANCELLED; PENDING_APPROVAL -> DRAFT (rejected) | SENDING (approved, in the same
--   statement) | CANCELLED; SENDING -> SENT; SENT and CANCELLED are final), so what was
--   sent can never be reopened. reference, created_at and (once set) sent_at are frozen;
--   rejection_reason is written only when a pending campaign is rejected.
CREATE FUNCTION notification_campaign_approval_guard() RETURNS trigger AS $$
DECLARE
  author uuid;
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NEW.approved_by IS NOT NULL OR NEW.approved_at IS NOT NULL THEN
      RAISE EXCEPTION 'notification_campaign: a campaign cannot be created approved';
    END IF;
    RETURN NEW;
  END IF;
  IF OLD.status <> 'DRAFT' AND (
       NEW.campaign_type IS DISTINCT FROM OLD.campaign_type
       OR NEW.message IS DISTINCT FROM OLD.message
       OR NEW.translations IS DISTINCT FROM OLD.translations
       OR NEW.channels IS DISTINCT FROM OLD.channels
       OR NEW.audience_filter IS DISTINCT FROM OLD.audience_filter
       OR NEW.template_id IS DISTINCT FROM OLD.template_id
       OR NEW.incident_id IS DISTINCT FROM OLD.incident_id) THEN
    -- escalate_after_s stays adjustable: a demo scene starts the check-in clock (D-07).
    RAISE EXCEPTION 'notification_campaign: the content is frozen once it leaves DRAFT';
  END IF;
  IF NEW.reference IS DISTINCT FROM OLD.reference
     OR NEW.created_at IS DISTINCT FROM OLD.created_at
     OR (OLD.sent_at IS NOT NULL AND NEW.sent_at IS DISTINCT FROM OLD.sent_at) THEN
    RAISE EXCEPTION 'notification_campaign: reference, created_at and sent_at cannot change';
  END IF;
  IF NEW.status IS DISTINCT FROM OLD.status AND NOT (
       (OLD.status = 'DRAFT' AND NEW.status IN ('PENDING_APPROVAL', 'SENDING', 'CANCELLED'))
       OR (OLD.status = 'PENDING_APPROVAL' AND NEW.status IN ('DRAFT', 'CANCELLED'))
       OR (OLD.status = 'PENDING_APPROVAL' AND NEW.status = 'SENDING'
           AND OLD.approved_by IS NULL AND NEW.approved_by IS NOT NULL)
       OR (OLD.status = 'SENDING' AND NEW.status = 'SENT')) THEN
    RAISE EXCEPTION 'notification_campaign: status cannot go from % to %', OLD.status, NEW.status;
  END IF;
  IF NEW.rejection_reason IS DISTINCT FROM OLD.rejection_reason
     AND NOT (OLD.status = 'PENDING_APPROVAL' AND NEW.status = 'DRAFT') THEN
    RAISE EXCEPTION 'notification_campaign: a rejection reason is written only on rejection';
  END IF;
  -- Approving sends: the approval moves the campaign on (to SENDING) in the same
  -- statement, and an approved campaign is never DRAFT or PENDING_APPROVAL again.
  IF NEW.approved_by IS NOT NULL AND NEW.status IN ('DRAFT', 'PENDING_APPROVAL') THEN
    RAISE EXCEPTION 'notification_campaign: an approved campaign cannot be %', NEW.status;
  END IF;
  IF NEW.created_by IS DISTINCT FROM OLD.created_by
     OR NEW.created_by_type IS DISTINCT FROM OLD.created_by_type THEN
    RAISE EXCEPTION 'notification_campaign: the author cannot change';
  END IF;
  IF OLD.submitted_by IS NOT NULL AND NEW.submitted_by IS DISTINCT FROM OLD.submitted_by THEN
    RAISE EXCEPTION 'notification_campaign: submitted_by cannot change once set';
  END IF;
  IF OLD.approved_by IS NOT NULL AND NEW.approved_by IS DISTINCT FROM OLD.approved_by THEN
    RAISE EXCEPTION 'notification_campaign: approved_by cannot change once set';
  END IF;
  IF OLD.approved_at IS NOT NULL AND NEW.approved_at IS DISTINCT FROM OLD.approved_at THEN
    RAISE EXCEPTION 'notification_campaign: approved_at cannot change once set';
  END IF;
  IF OLD.approved_by IS NULL AND NEW.approved_by IS NOT NULL THEN
    IF OLD.status <> 'PENDING_APPROVAL' THEN
      RAISE EXCEPTION 'notification_campaign: only a campaign pending approval can be approved';
    END IF;
    IF NEW.created_by_type = 'USER' THEN
      BEGIN
        author := NEW.created_by::uuid;
      EXCEPTION WHEN invalid_text_representation OR null_value_not_allowed THEN
        author := NULL;
      END;
      IF author IS NULL THEN
        RAISE EXCEPTION 'notification_campaign: the author is unknown, so it cannot be approved';
      END IF;
      IF NEW.approved_by = author THEN
        RAISE EXCEPTION 'notification_campaign: the author cannot approve their own campaign (D-31)';
      END IF;
    END IF;
    IF NEW.approved_by = NEW.submitted_by THEN
      RAISE EXCEPTION 'notification_campaign: the author cannot approve their own campaign (D-31)';
    END IF;
    IF NEW.status <> 'SENDING' THEN
      RAISE EXCEPTION 'notification_campaign: approving moves the campaign to SENDING';
    END IF;
    NEW.approved_at := now();  -- PC-11 (3): never a time supplied by the caller
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER notification_campaign_approval_guard
  BEFORE INSERT OR UPDATE ON notification_campaign
  FOR EACH ROW EXECUTE FUNCTION notification_campaign_approval_guard();

-- PC-10 (6): no code deletes campaigns, and a deletion would cascade to the deliveries
-- and check-in answers that are the evidence of what was sent.
REVOKE DELETE ON notification_campaign FROM nexira_app;
-- PC-11 (4): nor the deliveries and check-in answers themselves (no code deletes them).
REVOKE DELETE ON notification_delivery, checkin_response FROM nexira_app;

-- PC-12 (4): check-in answers are an append-only history (D-07); no code updates them.
REVOKE UPDATE ON checkin_response FROM nexira_app;
-- A delivery stays with its campaign, person and channel; only its progress changes
-- (status, provider_ref, updated_at, written by the dispatcher).
CREATE FUNCTION notification_delivery_guard() RETURNS trigger AS $$
BEGIN
  IF NEW.campaign_id IS DISTINCT FROM OLD.campaign_id
     OR NEW.person_id IS DISTINCT FROM OLD.person_id
     OR NEW.channel IS DISTINCT FROM OLD.channel
     OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id THEN
    RAISE EXCEPTION 'notification_delivery: campaign, person and channel cannot change';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER notification_delivery_guard BEFORE UPDATE ON notification_delivery
  FOR EACH ROW EXECUTE FUNCTION notification_delivery_guard();
