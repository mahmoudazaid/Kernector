import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import { NotFoundState } from "@/components/states/NotFoundState";
import { UnavailableState } from "@/components/states/UnavailableState";

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: {
    href: string;
    children: React.ReactNode;
    [key: string]: unknown;
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

describe("global UI states", () => {
  it("shows a loading shell message", () => {
    render(<LoadingState />);

    expect(
      screen.getByRole("heading", { name: /loading page shell/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/keeps the surrounding navigation available/i),
    ).toBeInTheDocument();
  });

  it("shows a neutral empty state", () => {
    render(<EmptyState />);

    expect(
      screen.getByRole("heading", { name: /nothing here yet/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/feature-specific actions belong to later tickets/i),
    ).toBeInTheDocument();
  });

  it("shows a safe error alert with try again", async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();

    render(<ErrorState onRetry={onRetry} />);

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: /something went wrong/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/without exposing internal details/i),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /try again/i }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("shows not found with a return home action", () => {
    render(<NotFoundState />);

    expect(
      screen.getByRole("heading", { name: /page not found/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /return to dashboard/i }),
    ).toHaveAttribute("href", "/");
  });

  it("shows unavailable placeholder messaging", () => {
    render(<UnavailableState />);

    expect(
      screen.getByRole("heading", { name: /feature unavailable/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/intentionally a placeholder until its implementation ticket/i),
    ).toBeInTheDocument();
  });
});
