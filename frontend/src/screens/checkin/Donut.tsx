// A ring chart of personnel answers (safe, need help, pending), as in the demo.
const R = 66;
const C = 2 * Math.PI * R;

export function Donut({ values, colours, label }: { values: number[]; colours: string[]; label: string }) {
  const total = values.reduce((a, b) => a + b, 0) || 1;
  const lengths = values.map((v) => (v / total) * C);
  const offsets = lengths.map((_, i) => lengths.slice(0, i).reduce((a, b) => a + b, 0));
  return (
    <svg width={160} height={160} viewBox="0 0 170 170" role="img" aria-label={label}>
      <circle cx={85} cy={85} r={R} fill="none" stroke="#2F343C" strokeWidth={14} />
      {lengths.map((length, i) => (
        <circle
          key={i}
          cx={85}
          cy={85}
          r={R}
          fill="none"
          stroke={colours[i]}
          strokeWidth={14}
          strokeDasharray={`${length} ${C - length}`}
          strokeDashoffset={-(offsets[i] ?? 0)}
          transform="rotate(-90 85 85)"
          className="nx-donut-arc"
        />
      ))}
    </svg>
  );
}
