import type { ComponentProps } from "react";

import { type FlashTone, useCountUp, useFlash } from "./useMotion";

export type { FlashTone } from "./useMotion";

/** A table row that flashes in `tone` when `watch` (what the row shows) changes. */
export function FlashRow({
  watch,
  tone = "info",
  className,
  ...rest
}: ComponentProps<"tr"> & { watch: string; tone?: FlashTone }) {
  const flash = useFlash(watch);
  const classes = [className, flash && `${flash} nx-tone-${tone}`].filter(Boolean).join(" ");
  return <tr className={classes || undefined} {...rest} />;
}

function decimals(n: number): number {
  return Number.isInteger(n) ? 0 : (String(n).split(".")[1]?.length ?? 0);
}

/** A number that counts to its new value instead of jumping (en-GB grouping, as elsewhere). */
export function CountUp({ value, ms }: { value: number; ms?: number }) {
  const shown = useCountUp(value, ms);
  const digits = decimals(value);
  return (
    <>
      {shown.toLocaleString("en-GB", {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      })}
    </>
  );
}
