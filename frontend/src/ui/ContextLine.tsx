import type { ReactNode } from "react";

/** DC-06 (D-56; plan G-8): what the screen's data is, in one line above the tiles, with any
 *  screen-wide action on the right. Warnings that need action stay banners. */
export function ContextLine({ children, actions }: { children: ReactNode; actions?: ReactNode }) {
  return (
    <div className="nx-context" role="note">
      <span className="nx-context-text">{children}</span>
      {actions && <span className="nx-context-actions">{actions}</span>}
    </div>
  );
}
