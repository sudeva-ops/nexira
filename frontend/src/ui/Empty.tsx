import type { ReactNode } from "react";

/** DC-03 (D-56; plan G-6): "nothing here yet" inside a panel. One dim sentence in the body font
 *  that says what will appear and when. A whole-page NonIdealState is only for a screen that
 *  cannot work: a load error, no access, or a record not found. */
export function Empty({ children, label }: { children: ReactNode; label?: string }) {
  return (
    <div className="nx-empty" aria-label={label}>
      {children}
    </div>
  );
}
