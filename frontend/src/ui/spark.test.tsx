import { render, screen } from "@testing-library/react";

import { Ring } from "./Ring";
import { SkeletonRows } from "./Skeleton";
import { Kpi } from "./primitives";
import { buckets, hasHistory, months, remaining, ringTone, sums } from "./spark";
import { Sparkline } from "./Sparkline";

const NOW = Date.parse("2026-10-30T12:00:00Z");
const ago = (min: number) => new Date(NOW - min * 60_000).toISOString();

describe("buckets", () => {
  it("counts events per bucket, oldest first, ignoring those outside the window", () => {
    const times = [ago(1), ago(2), ago(14), ago(59), ago(61), new Date(NOW + 60_000).toISOString()];
    expect(buckets(times, NOW, 3_600_000, 4)).toEqual([1, 0, 0, 3]);
  });
});

describe("sums (DC-02)", () => {
  it("adds each item's own count in the bucket of its time", () => {
    const now = Date.parse("2026-11-12T12:00:00Z");
    const at = (h: number) => new Date(now - h * 3_600_000).toISOString();
    expect(sums([{ at: at(0.5), n: 40 }, { at: at(0.7), n: 2 }, { at: at(2.5), n: 5 }, { at: at(30), n: 9 }], now, 4 * 3_600_000, 4)).toEqual([
      0, 5, 0, 42,
    ]);
  });
});

describe("months (DC-02)", () => {
  it("counts this year's times per month, January to now", () => {
    const now = Date.parse("2026-04-20T00:00:00Z");
    expect(
      months(["2026-01-03T00:00:00Z", "2026-03-31T23:00:00Z", "2026-03-01T00:00:00Z", "2025-12-30T00:00:00Z", "2026-05-01T00:00:00Z"], now),
    ).toEqual([1, 0, 2, 0]);
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

describe("sparklines in the stat tiles (GFX-07)", () => {
  it("draws nothing without history, never a made-up line", () => {
    expect(hasHistory([])).toBe(false);
    expect(hasHistory([0, 0, 0])).toBe(false);
    expect(hasHistory([0, 2, 0])).toBe(true);
    const { rerender } = render(
      <Kpi icon="feed" label="Signals" value={0} trend={{ values: [0, 0, 0], label: "Signals per hour" }} />,
    );
    expect(screen.queryByRole("img", { name: "Signals per hour" })).toBeNull();
    rerender(<Kpi icon="feed" label="Signals" value={3} trend={{ values: [0, 1, 2], label: "Signals per hour" }} />);
    expect(screen.getByRole("img", { name: "Signals per hour" })).toBeInTheDocument();
  });

  it("draws illustrative points fainter, joined to the live line (GFX-05)", () => {
    render(<Sparkline values={[1, 2, 3, 4, 5]} faint={2} label="trend" />);
    const lines = screen.getByRole("img", { name: "trend" }).querySelectorAll("polyline");
    expect(lines).toHaveLength(2);
    expect(lines[0]?.getAttribute("class")).toBe("faint");
    expect(lines[0]?.getAttribute("points")?.split(" ")).toHaveLength(3); // up to the first live point
    expect(lines[1]?.getAttribute("points")?.split(" ")).toHaveLength(3);
  });
});
