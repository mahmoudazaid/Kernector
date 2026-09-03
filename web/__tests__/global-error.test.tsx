import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { GlobalErrorFallback } from "@/app/global-error";

describe("root global error boundary", () => {
  it("shows a safe alert message without exposing internal details", () => {
    render(<GlobalErrorFallback onRetry={() => undefined} />);

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
    const onRetry = vi.fn();

    render(<GlobalErrorFallback onRetry={onRetry} />);

    const retry = screen.getByRole("button", { name: /try again/i });
    expect(retry).toBeEnabled();
    await user.click(retry);
    expect(onRetry).toHaveBeenCalledOnce();
  });
});
