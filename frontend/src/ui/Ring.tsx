import type { FlashTone } from "./useMotion";

const R = 6;
const C = 2 * Math.PI * R;

/** A small ring that empties as time runs out (a decision deadline, a partner's ETA). */
export function Ring({ left, tone = "info", label }: { left: number; tone?: FlashTone; label: string }) {
  return (
    <svg className={`nx-ring nx-tone-${tone}`} viewBox="0 0 16 16" width={14} height={14} role="img" aria-label={label}>
      <circle cx={8} cy={8} r={R} className="track" />
      <circle
        cx={8}
        cy={8}
        r={R}
        className="left"
        strokeDasharray={C}
        strokeDashoffset={C * (1 - left)}
        transform="rotate(-90 8 8)"
      />
    </svg>
  );
}
