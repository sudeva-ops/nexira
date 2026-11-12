import type { ReactNode } from "react";

/** DC-01, DC-08 (D-56): a screen's row of 4 to 6 stat tiles (Kpi), the same on every screen. Its
 *  parent's gap spaces it, as for every other block on the page. */
export function TileRow({
  children,
  columns = 4,
  label = "Figures",
}: {
  children: ReactNode;
  columns?: 4 | 5 | 6;
  label?: string;
}) {
  return (
    <div className={`nx-tiles nx-tiles-${columns}`} role="group" aria-label={label}>
      {children}
    </div>
  );
}
