import { Button, InputGroup } from "@blueprintjs/core";
import { useState } from "react";

import { ApiError } from "../../api/client";
import {
  type DeliveryStatus,
  type NtfCampaign,
  useCampaignAction,
  useCampaignPermissions,
  useRejectCampaign,
} from "../../api/notifications";
import { formatStamp } from "../../app/time";
import { Card } from "../../ui/primitives";

const CHANNEL_NAME: Record<string, string> = {
  APP: "App push",
  SMS: "SMS",
  WHATSAPP: "WhatsApp",
  VOICE: "Voice call",
  EMAIL: "Email",
};
// Read, then delivered, then sent or queued, then failed (MN-09).
const SEGMENTS: [DeliveryStatus[], string, string][] = [
  [["READ"], "Read", "#32A467"],
  [["DELIVERED"], "Delivered", "#2D72D2"],
  [["SENT", "QUEUED"], "Sending", "#5F6B7C"],
  [["FAILED"], "Failed", "#CD4246"],
];
const STATUS_LABEL: Record<string, string> = {
  DRAFT: "Draft",
  PENDING_APPROVAL: "Awaiting approval",
  SENDING: "Sending",
  SENT: "Sent",
  CANCELLED: "Cancelled",
};

function sum(counts: Partial<Record<DeliveryStatus, number>>, statuses: DeliveryStatus[]): number {
  return statuses.reduce((n, s) => n + (counts[s] ?? 0), 0);
}

/** MN-09: per channel, how far each delivery got. Updated live over the WebSocket. */
export function Funnel({ campaign }: { campaign: NtfCampaign }) {
  return (
    <div aria-label="Delivery funnel">
      <div className="nx-funnel-legend">
        {SEGMENTS.map(([, label, colour]) => (
          <span key={label}>
            <i style={{ background: colour }} />
            {label}
          </span>
        ))}
      </div>
      {campaign.channels.map((channel) => {
        const counts = campaign.funnel[channel] ?? {};
        const total = sum(counts, ["QUEUED", "SENT", "DELIVERED", "READ", "FAILED"]);
        return (
          <div key={channel} className="nx-funnel" aria-label={`${CHANNEL_NAME[channel] ?? channel} funnel`}>
            <span>{CHANNEL_NAME[channel] ?? channel}</span>
            <div className="nx-stack">
              {total > 0 &&
                SEGMENTS.map(([statuses, label, colour]) => (
                  <i
                    key={label}
                    style={{ width: `${(sum(counts, statuses) / total) * 100}%`, background: colour }}
                  />
                ))}
            </div>
            <span className="nx-mono nx-dim">
              {total ? `${sum(counts, ["READ"])}/${total} read` : "—"}
            </span>
          </div>
        );
      })}
    </div>
  );
}

export function CampaignDetail({
  campaign,
  onEdit,
}: {
  campaign: NtfCampaign;
  onEdit: (campaign: NtfCampaign) => void;
}) {
  const allowed = useCampaignPermissions(campaign.id).data;
  const action = useCampaignAction();
  const reject = useRejectCampaign();
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const run = (verb: "submit" | "approve" | "cancel") => action.mutate({ id: campaign.id, action: verb });
  const error = action.error ?? reject.error;
  const author = campaign.created_by_type === "USER" ? campaign.created_by_name : campaign.created_by_type.toLowerCase();

  return (
    <Card
      icon="chart"
      title={`${campaign.reference} · ${STATUS_LABEL[campaign.status] ?? campaign.status}`}
      sub={`${campaign.recipients.toLocaleString("en-GB")} recipients · ${campaign.channels.length} channels`}
    >
      <div className="nx-bd">
        <p className="nx-ntf-message">{campaign.message}</p>
        {Object.keys(campaign.translations).length > 0 && (
          <div className="nx-dim">Also in: {Object.keys(campaign.translations).join(", ").toUpperCase()}</div>
        )}
        <div className="nx-dim">
          By {author ?? "—"} · {formatStamp(campaign.created_at)}
          {campaign.approved_by_name && ` · approved by ${campaign.approved_by_name}`}
        </div>
        {campaign.rejection_reason && campaign.status === "DRAFT" && (
          <div className="nx-pending">Returned: {campaign.rejection_reason}</div>
        )}
        <Funnel campaign={campaign} />

        {allowed && (
          <div className="nx-row nx-detail-actions">
            {allowed.edit_campaign && <Button text="Edit" onClick={() => onEdit(campaign)} />}
            {allowed.approve_campaign && !rejecting && (
              <>
                <Button
                  intent="primary"
                  icon="tick"
                  text="Approve and send"
                  loading={action.isPending}
                  onClick={() => run("approve")}
                />
                <Button text="Reject" onClick={() => setRejecting(true)} />
              </>
            )}
            {rejecting && (
              <>
                <InputGroup
                  aria-label="Reason for rejecting"
                  placeholder="Reason (sent back to the author)"
                  value={reason}
                  maxLength={500}
                  onChange={(e) => setReason(e.currentTarget.value)}
                />
                <Button
                  intent="danger"
                  text="Send back"
                  disabled={!reason.trim()}
                  loading={reject.isPending}
                  onClick={() =>
                    reject.mutate(
                      { id: campaign.id, reason },
                      { onSuccess: () => (setRejecting(false), setReason("")) },
                    )
                  }
                />
                <Button minimal text="Keep" onClick={() => setRejecting(false)} />
              </>
            )}
            <span className="nx-grow" />
            {allowed.cancel_campaign && (
              <Button minimal intent="danger" text="Cancel campaign" onClick={() => run("cancel")} />
            )}
          </div>
        )}
        {error && (
          <div className="nx-error">{error instanceof ApiError ? error.message : "Not done"}</div>
        )}
      </div>
    </Card>
  );
}
