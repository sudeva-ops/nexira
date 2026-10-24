import { Button, Spinner, Tag } from "@blueprintjs/core";

import { roleLabel, useMe } from "../api/me";

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
      <Button icon="log-out" variant="minimal" aria-label="Sign out" onClick={onLogout} />
    </div>
  );
}
