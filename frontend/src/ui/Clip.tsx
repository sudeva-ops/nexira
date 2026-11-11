/** UIP-03: one line, cut with an ellipsis when it does not fit, and the full text on hover. */
export function Clip({ text, className }: { text: string; className?: string }) {
  return (
    <span className={`nx-clip${className ? ` ${className}` : ""}`} title={text}>
      {text}
    </span>
  );
}
