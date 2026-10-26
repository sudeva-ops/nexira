import { HTMLSelect } from "@blueprintjs/core";
import { useState } from "react";

import type { Rendered } from "../../api/notifications";

const CHANNEL_NAME: Record<string, string> = {
  APP: "App push",
  SMS: "SMS",
  WHATSAPP: "WhatsApp",
  VOICE: "Voice call",
  EMAIL: "Email",
};

/** MN-08: "Send test to me" shows each channel as it would arrive. Nothing is sent. */
export function TestPhone({ rendered }: { rendered: Rendered }) {
  const channels = Object.keys(rendered);
  const [channel, setChannel] = useState(channels[0] ?? "");
  const shown = rendered[channel];
  return (
    <div className="nx-testphone">
      <div className="nx-phone-label">
        TEST TO YOU ·{" "}
        <HTMLSelect
          minimal
          aria-label="Test channel"
          value={channel}
          onChange={(e) => setChannel(e.currentTarget.value)}
          options={channels.map((c) => ({ value: c, label: CHANNEL_NAME[c] ?? c }))}
        />
      </div>
      <div className="nx-phone" aria-label="Test preview">
        <div className="notch" />
        <div className="scr">
          {shown?.title && <b>{shown.title}</b>}
          {shown?.subject && <b>{shown.subject}</b>}
          <p>{shown?.body ?? shown?.text ?? shown?.script}</p>
          {shown?.sms_segments !== undefined && (
            <span className="nx-dim">
              {shown.sms_segments} SMS segment{shown.sms_segments === 1 ? "" : "s"}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
