import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import GlobalError from "@/app/global-error";

describe("root global error boundary", () => {
  it("shows a safe alert message without exposing internal details", () => {
    const secret = new Error("OPENROUTER_API_KEY=sk-leak stack at env.ts:12");

    render(
      <GlobalError error={secret} reset={() => undefined} />,
    );

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: /something went wrong/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/without exposing internal details/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/OPENROUTER_API_KEY/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/sk-leak/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/env\.ts/i)).not.toBeInTheDocument();
  });

  it("provides a keyboard-accessible retry action", async () => {
    const user = userEvent.setup();
    const reset = vi.fn();

    render(
      <GlobalError
        error={new Error("boom")}
        reset={reset}
      />,
    );

    const retry = screen.getByRole("button", { name: /try again/i });
    expect(retry).toBeEnabled();
    await user.click(retry);
    expect(reset).toHaveBeenCalledOnce();
  });
});
