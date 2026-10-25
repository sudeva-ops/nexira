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

-- Database backstop for D-31, as proposal_approval has for D-16: the author (or the
-- submitter) never approves their own campaign, and an approval is never rewritten.
CREATE FUNCTION notification_campaign_approval_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'UPDATE' AND OLD.approved_by IS NOT NULL
     AND NEW.approved_by IS DISTINCT FROM OLD.approved_by THEN
    RAISE EXCEPTION 'notification_campaign: approved_by cannot change once set';
  END IF;
  IF NEW.approved_by IS NOT NULL
     AND ((NEW.created_by_type = 'USER' AND NEW.approved_by::text = NEW.created_by)
          OR NEW.approved_by = NEW.submitted_by) THEN
    RAISE EXCEPTION 'notification_campaign: the author cannot approve their own campaign (D-31)';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER notification_campaign_approval_guard
  BEFORE INSERT OR UPDATE ON notification_campaign
  FOR EACH ROW EXECUTE FUNCTION notification_campaign_approval_guard();
