/** A tiny line of counts over time; the last point is marked. Plain SVG. The first `faint`
 *  points are illustrative and drawn lighter (GFX-05, GFX-07). */
export function Sparkline({
  values,
  label,
  width = 64,
  height = 16,
  faint = 0,
}: {
  values: number[];
  label: string;
  width?: number;
  height?: number;
  faint?: number;
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
      {faint > 0 && (
        <polyline
          className="faint"
          points={points.slice(0, faint + 1).map(([x, y]) => `${x},${y}`).join(" ")}
        />
      )}
      <polyline points={points.slice(Math.max(0, faint)).map(([x, y]) => `${x},${y}`).join(" ")} />
      {last && <circle cx={last[0]} cy={last[1]} r={1.8} />}
    </svg>
  );
}
