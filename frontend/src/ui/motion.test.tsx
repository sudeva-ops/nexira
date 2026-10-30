import { act, render, screen } from "@testing-library/react";
import { vi } from "vitest";

import { CountUp, FlashRow } from "./motion";
import { useFlash } from "./useMotion";

function Flashing({ watch }: { watch: string }) {
  return <span data-testid="f" className={useFlash(watch)} />;
}

function Row({ watch }: { watch: string }) {
  return (
    <table>
      <tbody>
        <FlashRow watch={watch} tone="danger" className="on" data-testid="row">
          <td>x</td>
        </FlashRow>
      </tbody>
    </table>
  );
}

/** matchMedia answering `reduce` for prefers-reduced-motion. */
function motionPreference(reduce: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches: reduce && query.includes("reduce"),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("useFlash", () => {
  it("does not flash on first show, and alternates classes so each change replays", () => {
    const { rerender } = render(<Flashing watch="ACCEPTED" />);
    expect(screen.getByTestId("f").className).toBe("");
    rerender(<Flashing watch="ACCEPTED" />);
    expect(screen.getByTestId("f").className).toBe("");
    rerender(<Flashing watch="EN_ROUTE" />);
    expect(screen.getByTestId("f").className).toBe("nx-flash-a");
    rerender(<Flashing watch="COMPLETED" />);
    expect(screen.getByTestId("f").className).toBe("nx-flash-b");
  });
});

describe("FlashRow", () => {
  it("keeps the row's own class and adds the flash and its tone only on change", () => {
    const { rerender } = render(<Row watch="HOLDING" />);
    expect(screen.getByTestId("row").className).toBe("on");
    rerender(<Row watch="DIVERTED" />);
    expect(screen.getByTestId("row").className).toBe("on nx-flash-a nx-tone-danger");
  });
});

describe("CountUp", () => {
  it("shows the first value at once, with en-GB grouping", () => {
    motionPreference(false);
    render(<CountUp value={1240} />);
    expect(screen.getByText("1,240")).toBeInTheDocument();
  });

  it("counts to a new value over the animation, then shows it exactly", () => {
    motionPreference(false);
    vi.useFakeTimers({
      toFake: ["requestAnimationFrame", "cancelAnimationFrame", "performance"],
    });
    const { container, rerender } = render(<CountUp value={0} ms={600} />);
    rerender(<CountUp value={100} ms={600} />);
    expect(container.textContent).toBe("0");
    act(() => vi.advanceTimersByTime(300));
    const midway = Number(container.textContent);
    expect(midway).toBeGreaterThan(0);
    expect(midway).toBeLessThan(100);
    act(() => vi.advanceTimersByTime(400));
    expect(container.textContent).toBe("100");
  });

  it("jumps straight to the new value when reduced motion is asked for", () => {
    motionPreference(true);
    const { container, rerender } = render(<CountUp value={3} />);
    rerender(<CountUp value={7} />);
    expect(container.textContent).toBe("7");
  });

  it("does not animate when the browser cannot report a motion preference", () => {
    const { container, rerender } = render(<CountUp value={3} />);
    rerender(<CountUp value={9} />);
    expect(container.textContent).toBe("9");
  });
});
