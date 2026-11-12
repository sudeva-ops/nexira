import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { DETAIL, MISSIONS } from "../test/fixtures";
import { MiniMap } from "./MiniMap";

const created = vi.hoisted(() => [] as Record<string, unknown>[]);
vi.mock("maplibre-gl", () => ({
  Map: class {
    constructor(options: Record<string, unknown>) {
      created.push(options);
    }
    on() {}
    remove() {}
  },
}));
vi.mock("./base", () => ({
  registerPmtiles: () => {},
  tilesAvailable: () => Promise.resolve({ base: true, imagery: true }),
}));

function Where() {
  const at = useLocation();
  return <div data-testid="where">{at.pathname + at.search}</div>;
}

describe("MiniMap (GFX-08)", () => {
  it("is a still, flat view at city zoom, and a click opens Global Operations on the incident", async () => {
    render(
      <MemoryRouter initialEntries={["/incidents"]}>
        <Routes>
          <Route path="/incidents" element={<MiniMap incident={DETAIL} missions={MISSIONS} />} />
          <Route path="/operations" element={<Where />} />
        </Routes>
      </MemoryRouter>,
    );
    await vi.waitFor(() => expect(created).toHaveLength(1));
    expect(created[0]).toMatchObject({ interactive: false, zoom: 12, center: [DETAIL.lon, DETAIL.lat] });
    expect(created[0]).not.toHaveProperty("projection");
    await userEvent.click(screen.getByRole("button", { name: `Open ${DETAIL.reference} in Global Operations` }));
    expect(screen.getByTestId("where")).toHaveTextContent(`/operations?incident=${DETAIL.id}`);
  });
});
