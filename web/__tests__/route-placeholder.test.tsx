import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RoutePlaceholder } from "@/components/placeholders/RoutePlaceholder";
import { NAV_ITEMS } from "@/lib/navigation";

describe("placeholder routes", () => {
  it.each(NAV_ITEMS)(
    "renders $label as a planned placeholder without feature UI",
    ({ label }) => {
      render(<RoutePlaceholder title={label} />);

      expect(
        screen.getByRole("heading", { level: 1, name: label }),
      ).toBeInTheDocument();
      expect(screen.getByText("PLANNED")).toBeInTheDocument();
      expect(
        screen.getByRole("heading", { level: 2, name: /feature unavailable/i }),
      ).toBeInTheDocument();
      expect(
        screen.getByText(
          /no metrics, forms, chat behavior, or mocked business data/i,
        ),
      ).toBeInTheDocument();

      expect(screen.queryByRole("form")).not.toBeInTheDocument();
      expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
      expect(screen.queryByRole("table")).not.toBeInTheDocument();
      expect(screen.queryByText(/total documents/i)).not.toBeInTheDocument();
    },
  );
});
