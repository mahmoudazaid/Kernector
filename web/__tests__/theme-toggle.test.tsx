import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

const setTheme = vi.fn();
let theme = "light";

vi.mock("next-themes", () => ({
  useTheme: () => ({
    theme,
    resolvedTheme: theme,
    setTheme: (next: string) => {
      theme = next;
      setTheme(next);
    },
  }),
  ThemeProvider: ({ children }: { children: React.ReactNode }) => (
    <>{children}</>
  ),
}));

import { ThemeToggle } from "@/components/shell/ThemeToggle";

describe("theme foundation", () => {
  it("toggles between light and dark themes", async () => {
    theme = "light";
    setTheme.mockClear();
    const user = userEvent.setup();

    const { rerender } = render(
      <div data-theme={theme}>
        <ThemeToggle />
      </div>,
    );

    expect(
      document.querySelector("[data-theme]")?.getAttribute("data-theme"),
    ).toBe("light");

    await user.click(
      screen.getByRole("button", { name: /toggle color theme/i }),
    );
    expect(setTheme).toHaveBeenCalledWith("dark");

    theme = "dark";
    rerender(
      <div data-theme={theme}>
        <ThemeToggle />
      </div>,
    );

    expect(
      document.querySelector("[data-theme]")?.getAttribute("data-theme"),
    ).toBe("dark");
  });
});
