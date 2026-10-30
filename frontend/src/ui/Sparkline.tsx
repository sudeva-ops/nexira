/** A tiny line of counts over time; the last point is marked. Plain SVG. */
export function Sparkline({
  values,
  label,
  width = 64,
  height = 16,
}: {
  values: number[];
  label: string;
  width?: number;
  height?: number;
}) {
  const max = Math.max(1, ...values);
  const step = values.length > 1 ? width / (values.length - 1) : 0;
  const points = values.map((v, i) => [i * step, height - 1 - (v / max) * (height - 2)] as const);
  const last = points[points.length - 1];
  return (
    <svg
      className="nx-spark"
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      role="img"
      aria-label={label}
    >
      <polyline points={points.map(([x, y]) => `${x},${y}`).join(" ")} />
      {last && <circle cx={last[0]} cy={last[1]} r={1.8} />}
    </svg>
  );
}
