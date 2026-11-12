import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ContextLine } from "./ContextLine";
import { Empty } from "./Empty";
import { plural } from "./format";
import { Card, Kpi } from "./primitives";
import { TileRow } from "./TileRow";

// The shared pieces of the design consistency module (D-56, DC-01..DC-08).

describe("plural (DC-05)", () => {
  it("says the noun in the right number", () => {
    expect(plural(1, "incident")).toBe("1 incident");
    expect(plural(0, "incident")).toBe("0 incidents");
    expect(plural(2, "entry", "entries")).toBe("2 entries");
    expect(plural(1338, "person", "people")).toBe("1,338 people");
  });
});

describe("Card's chip (DC-05)", () => {
  it("draws at most one chip in the header, with a dot for a tone", () => {
    render(
      <Card title="Live responses" chip={{ text: "Live", tone: "live" }}>
        body
      </Card>,
    );
    const header = screen.getByRole("heading", { name: "Live responses" }).closest("header");
    expect(header).not.toBeNull();
    const chips = header?.querySelectorAll(".nx-chip") ?? [];
    expect(chips).toHaveLength(1);
    expect(chips[0]).toHaveTextContent("Live");
    expect(chips[0]?.getAttribute("data-tone")).toBe("live");
    expect(chips[0]?.querySelector("i")).not.toBeNull();
  });

  it("has no chip unless asked, and no dot without a tone", () => {
    const { container, rerender } = render(<Card title="Plain">x</Card>);
    expect(container.querySelector(".nx-chip")).toBeNull();
    rerender(
      <Card title="Count" chip={{ text: plural(3, "playbook") }}>
        x
      </Card>,
    );
    expect(container.querySelector(".nx-chip")).toHaveTextContent("3 playbooks");
    expect(container.querySelector(".nx-chip i")).toBeNull();
  });
});

describe("Empty (DC-03)", () => {
  it("is one sentence in the body font, not a page-filling state", () => {
    const { container } = render(<Empty label="Recent movements">No movement recorded yet.</Empty>);
    const empty = screen.getByLabelText("Recent movements");
    expect(empty).toHaveTextContent("No movement recorded yet.");
    expect(empty).toHaveClass("nx-empty");
    expect(container.querySelector(".bp6-non-ideal-state")).toBeNull();
  });
});

describe("ContextLine (DC-06)", () => {
  it("says what the data is, with the screen's action on the right", () => {
    render(<ContextLine actions={<button type="button">Export briefing</button>}>Worked out from live data</ContextLine>);
    const line = screen.getByRole("note");
    expect(line).toHaveTextContent("Worked out from live data");
    expect(within(line).getByRole("button", { name: "Export briefing" })).toBeInTheDocument();
  });
});

describe("TileRow (DC-01)", () => {
  it("holds the screen's tiles in 4, 5 or 6 columns", () => {
    render(
      <TileRow columns={5} label="Exercise figures">
        <Kpi icon="tick" label="Safe" value={3} />
        <Kpi icon="help" label="Need help" value={1} />
      </TileRow>,
    );
    const row = screen.getByRole("group", { name: "Exercise figures" });
    expect(row).toHaveClass("nx-tiles", "nx-tiles-5");
    expect(within(row).getByText("Need help")).toBeInTheDocument();
  });
});
