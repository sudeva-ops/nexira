import { Button, Spinner, Tag } from "@blueprintjs/core";
import { useSyncExternalStore } from "react";

import { roleLabel, useMe } from "../api/me";
import { calmNow, setCalm, subscribeCalm } from "../ui/calm";

/** UI 3: Calm mode turns all motion off, kept in this browser. */
function CalmSwitch() {
  const calm = useSyncExternalStore(subscribeCalm, calmNow, () => false);
  return (
    <Button
      icon={calm ? "pause" : "pulse"}
      variant="minimal"
      aria-label="Calm mode"
      aria-pressed={calm}
      title={calm ? "Calm mode: motion off (click for the live view)" : "Live view (click for Calm mode)"}
      onClick={() => setCalm(!calm)}
    />
  );
}

interface Props {
  onLogout: () => void;
}

export function UserMenu({ onLogout }: Props) {
  const me = useMe();

  if (me.isPending) return <Spinner size={16} />;
  if (me.isError) {
    return (
      <Tag intent="danger" minimal>
        Not signed in
      </Tag>
    );
  }

  return (
    <div className="nx-user">
      <div className="nx-user-text">
        <b data-testid="user-name">{me.data.display_name}</b>
        <span className="nx-user-roles" data-testid="user-roles">
          {me.data.roles.length === 0
            ? "No roles assigned"
            : me.data.roles.map((r) => (
                <Tag key={roleLabel(r)} minimal>
                  {roleLabel(r)}
                </Tag>
              ))}
        </span>
      </div>
      <CalmSwitch />
      <Button icon="log-out" variant="minimal" aria-label="Sign out" onClick={onLogout} />
    </div>
  );
}
