import { render, screen } from "@testing-library/react";

import { Ring } from "./Ring";
import { SkeletonRows } from "./Skeleton";
import { buckets, remaining, ringTone } from "./spark";
import { Sparkline } from "./Sparkline";

const NOW = Date.parse("2026-10-30T12:00:00Z");
const ago = (min: number) => new Date(NOW - min * 60_000).toISOString();

describe("buckets", () => {
  it("counts events per bucket, oldest first, ignoring those outside the window", () => {
    const times = [ago(1), ago(2), ago(14), ago(59), ago(61), new Date(NOW + 60_000).toISOString()];
    expect(buckets(times, NOW, 3_600_000, 4)).toEqual([1, 0, 0, 3]);
  });
});

describe("remaining", () => {
  it("is the share of the window still to run, from 1 down to 0", () => {
    const from = ago(10);
    const to = new Date(NOW + 10 * 60_000).toISOString();
    expect(remaining(from, to, NOW)).toBe(0.5);
    expect(remaining(from, to, NOW + 20 * 60_000)).toBe(0);
    expect(remaining(from, to, NOW - 20 * 60_000)).toBe(1);
    expect(remaining(to, from, NOW)).toBe(0);
  });
});

describe("ringTone", () => {
  it("turns amber in the last quarter and red in the last tenth", () => {
    expect(ringTone(0.5)).toBe("info");
    expect(ringTone(0.25)).toBe("warning");
    expect(ringTone(0.1)).toBe("danger");
  });
});

describe("Ring and Sparkline", () => {
  it("draw the time left and a line of counts, labelled for screen readers", () => {
    const { container } = render(
      <>
        <Ring left={0.25} tone="warning" label="Time left to decide" />
        <Sparkline values={[0, 2, 1]} label="Exposure activity" width={40} height={10} />
      </>,
    );
    const ring = screen.getByRole("img", { name: "Time left to decide" });
    expect(ring).toHaveClass("nx-tone-warning");
    const left = ring.querySelector(".left");
    const c = Number(left?.getAttribute("stroke-dasharray"));
    expect(Number(left?.getAttribute("stroke-dashoffset"))).toBeCloseTo(c * 0.75);
    expect(screen.getByRole("img", { name: "Exposure activity" })).toBeInTheDocument();
    expect(container.querySelector("polyline")?.getAttribute("points")).toBe("0,9 20,1 40,5");
  });
});

describe("SkeletonRows", () => {
  it("shows placeholder lines while loading", () => {
    render(<SkeletonRows rows={3} />);
    expect(screen.getByRole("status", { name: "Loading" }).children).toHaveLength(3);
  });
});
