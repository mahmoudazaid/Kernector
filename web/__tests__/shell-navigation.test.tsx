import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const usePathname = vi.fn(() => "/");

vi.mock("next/navigation", () => ({
  usePathname: () => usePathname(),
}));

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

import { AppShell } from "@/components/shell/AppShell";

describe("shell navigation", () => {
  beforeEach(() => {
    usePathname.mockReturnValue("/");
  });

  it("shows Kernector brand and multi-source knowledge hub label", () => {
    render(
      <AppShell>
        <div>content</div>
      </AppShell>,
    );

    expect(
      screen.getByRole("link", { name: /kernector home/i }),
    ).toBeInTheDocument();
    expect(screen.getByText("Kernector")).toBeInTheDocument();
    expect(screen.getByText("Multi-source knowledge hub")).toBeInTheDocument();
  });

  it("exposes Dashboard, Documents, Chat, and Settings destinations", () => {
    render(
      <AppShell>
        <div>content</div>
      </AppShell>,
    );

    expect(screen.getByRole("link", { name: "Dashboard" })).toHaveAttribute(
      "href",
      "/",
    );
    expect(screen.getByRole("link", { name: "Documents" })).toHaveAttribute(
      "href",
      "/documents",
    );
    expect(screen.getByRole("link", { name: "Chat" })).toHaveAttribute(
      "href",
      "/chat",
    );
    expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute(
      "href",
      "/settings",
    );
  });

  it("marks the active route with aria-current", () => {
    usePathname.mockReturnValue("/documents");

    render(
      <AppShell>
        <div>content</div>
      </AppShell>,
    );

    expect(screen.getByRole("link", { name: "Documents" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "Dashboard" })).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("does not show pack-specific story or interview labels by default", () => {
    render(
      <AppShell>
        <div>content</div>
      </AppShell>,
    );

    expect(screen.queryByText(/story intelligence/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/interview/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/software delivery/i)).not.toBeInTheDocument();
  });

  it("toggles the mobile navigation open and closed", async () => {
    const user = userEvent.setup();

    render(
      <AppShell>
        <div>content</div>
      </AppShell>,
    );

    const sidebar = screen.getByRole("navigation", {
      name: /primary navigation/i,
    });
    expect(sidebar).not.toHaveClass("is-open");

    await user.click(screen.getByRole("button", { name: /open navigation/i }));
    expect(sidebar).toHaveClass("is-open");

    await user.click(screen.getByRole("button", { name: /close navigation/i }));
    expect(sidebar).not.toHaveClass("is-open");
  });
});
