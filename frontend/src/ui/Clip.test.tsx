import { render, screen } from "@testing-library/react";

import { Clip } from "./Clip";
import { Card } from "./primitives";

describe("text that may be cut (UIP-03)", () => {
  it("keeps the full text in the title", () => {
    render(<Clip text="Peter Mwangi-Ochieng" />);
    expect(screen.getByText("Peter Mwangi-Ochieng")).toHaveAttribute("title", "Peter Mwangi-Ochieng");
  });

  it("gives a card's title and subtitle their full text, and keeps actions together (UIP-02)", () => {
    render(
      <Card title="Sensors & systems" sub="Access control, CCTV and building systems (simulated)" actions={<button type="button">Open AAR</button>}>
        body
      </Card>,
    );
    expect(screen.getByRole("heading", { name: "Sensors & systems" })).toHaveAttribute("title", "Sensors & systems");
    expect(screen.getByText(/^Access control, CCTV/)).toHaveAttribute("title", "Access control, CCTV and building systems (simulated)");
    expect(screen.getByRole("button", { name: "Open AAR" }).parentElement).toHaveClass("nx-card-actions");
  });
});
