import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Labels } from "../../src/common/components/labels/Labels";

describe("Labels", () => {
  it("renders a placeholder when there are no labels", () => {
    render(<Labels labels={[]} />);
    expect(screen.getByText("Not set")).toBeInTheDocument();
  });

  it("collapses overflow behind a +N chip and expands on click", () => {
    render(<Labels labels={["a", "b", "c", "d"]} max={2} />);

    expect(screen.getByText("a")).toBeInTheDocument();
    expect(screen.queryByText("c")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Show all 4 labels" }));

    expect(screen.getByText("c")).toBeInTheDocument();
    expect(screen.getByText("d")).toBeInTheDocument();
    expect(screen.queryByText("+2")).not.toBeInTheDocument();
  });
});
