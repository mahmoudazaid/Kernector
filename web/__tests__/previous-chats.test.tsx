import { readFileSync } from "node:fs";
import path from "node:path";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PreviousChats } from "@/components/chat/PreviousChats";
import { formatTimestamp } from "@/lib/format/timestamp";
import {
  createConversation,
  getConversation,
  listConversations,
} from "@/lib/session/conversations";

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    title,
    className,
    ...props
  }: {
    href: string;
    children: React.ReactNode;
    title?: string;
    className?: string;
    [key: string]: unknown;
  }) => (
    <a href={href} title={title} className={className} {...props}>
      {children}
    </a>
  ),
}));

const GLOBALS_CSS = readFileSync(
  path.resolve(__dirname, "../app/globals.css"),
  "utf8",
);

describe("PreviousChats", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("hides the Chats heading for the empty state and shows it when history exists", () => {
    const { container, rerender } = render(<PreviousChats />);

    expect(screen.getByRole("region", { name: "Chats" })).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { level: 2, name: "Chats" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: /no chats yet/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/ask a question above to start your first conversation/i),
    ).toBeInTheDocument();

    const empty = container.querySelector(".kern-previous-chats-empty");
    expect(empty).not.toBeNull();
    expect(empty?.querySelector(".kern-state")).not.toBeNull();
    expect(empty?.querySelector(".kern-state-mark")).not.toBeNull();
    expect(GLOBALS_CSS).toMatch(
      /\.kern-previous-chats-empty\s*\{[^}]*place-items:\s*center/,
    );

    createConversation({
      title: "Saved thread",
      messages: [{ id: "1", role: "user", content: "Saved thread" }],
      draft: "",
    });
    rerender(<PreviousChats />);

    expect(
      screen.getByRole("heading", { level: 2, name: "Chats" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: /no chats yet/i }),
    ).not.toBeInTheDocument();
  });

  it("renders the Chats heading and open links for each conversation", () => {
    const older = createConversation({
      title: "Older chat",
      messages: [{ id: "1", role: "user", content: "Older chat" }],
      draft: "",
    });
    const newer = createConversation({
      title: "Newer chat",
      messages: [{ id: "2", role: "user", content: "Newer chat" }],
      draft: "",
    });

    render(<PreviousChats />);

    expect(
      screen.getByRole("heading", { level: 2, name: "Chats" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Newer chat/i })).toHaveAttribute(
      "href",
      `/chat/${newer.id}`,
    );
    expect(screen.getByRole("link", { name: /Older chat/i })).toHaveAttribute(
      "href",
      `/chat/${older.id}`,
    );
    expect(screen.queryByRole("link", { name: /new chat/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /new chat/i })).not.toBeInTheDocument();
  });

  it("uses a bullet-free list and a full-row link with a separate right-aligned time", () => {
    const created = createConversation({
      title: "A very long conversation title that should truncate in the UI",
      messages: [
        {
          id: "1",
          role: "user",
          content: "A very long conversation title that should truncate in the UI",
        },
      ],
      draft: "",
    });

    const { container } = render(<PreviousChats />);
    const list = container.querySelector(".kern-previous-chats-list");
    expect(list).not.toBeNull();
    expect(list).toHaveClass("kern-previous-chats-list");
    expect(list?.tagName).toBe("UL");
    expect(GLOBALS_CSS).toMatch(
      /\.kern-previous-chats-list\s*\{[^}]*list-style(?:-type)?:\s*none/,
    );
    expect(GLOBALS_CSS).toMatch(
      /\.kern-previous-chats-list\s*\{[^}]*padding:\s*0/,
    );

    const link = screen.getByRole("link", {
      name: /A very long conversation title/i,
    });
    expect(link).toHaveAttribute("href", `/chat/${created.id}`);
    expect(link).not.toHaveAttribute("title");
    expect(link).toHaveClass("kern-previous-chats-row");

    const title = link.querySelector(".kern-previous-chats-row-title");
    const time = link.querySelector("time.kern-previous-chats-row-time");
    expect(title).not.toBeNull();
    expect(time).not.toBeNull();
    expect(time?.tagName).toBe("TIME");
    expect(time).toHaveAttribute(
      "dateTime",
      new Date(created.updatedAt).toISOString(),
    );
    expect(time).toHaveTextContent(
      formatTimestamp(new Date(created.updatedAt).toISOString()),
    );
    expect(link.contains(title as Node)).toBe(true);
    expect(link.contains(time as Node)).toBe(true);

    expect(GLOBALS_CSS).toMatch(
      /\.kern-previous-chats-row-meta\s*\{[^}]*margin-inline-start:\s*auto/,
    );
    expect(GLOBALS_CSS).toMatch(
      /\.kern-previous-chats-row-time\s*\{[^}]*text-align:\s*right/,
    );
    expect(GLOBALS_CSS).toMatch(
      /\.kern-previous-chats\s*\{[^}]*--kern-chat-col:\s*48rem/,
    );
    expect(GLOBALS_CSS).toMatch(
      /\.kern-previous-chats\s*\{[^}]*max-width:\s*var\(--kern-chat-col\)/,
    );
    expect(GLOBALS_CSS).toMatch(
      /\.kern-previous-chats-card\s*\{[^}]*box-shadow:\s*var\(--kern-control-emboss\)/,
    );
    expect(GLOBALS_CSS).toMatch(
      /\.kern-previous-chats-card\s*\{[^}]*var\(--kern-control-sheen\)/,
    );
    expect(GLOBALS_CSS).toMatch(
      /\.kern-previous-chats-list\s*\{[^}]*gap:\s*var\(--kern-space-3\)/,
    );
    expect(container.querySelectorAll(".kern-previous-chats-card")).toHaveLength(
      1,
    );
    expect(container.querySelector(".kern-previous-chats-surface")).toBeNull();
    expect(GLOBALS_CSS).toMatch(
      /\.kern-previous-chats-row-title\s*\{[^}]*text-overflow:\s*ellipsis/,
    );
  });

  it("exposes a sibling overflow button that does not sit inside the row link", () => {
    createConversation({
      title: "Thread alpha",
      messages: [{ id: "1", role: "user", content: "Thread alpha" }],
      draft: "",
    });

    render(<PreviousChats />);

    const link = screen.getByRole("link", { name: /Thread alpha/i });
    const menuButton = screen.getByRole("button", {
      name: "Conversation actions for Thread alpha",
    });
    expect(link.contains(menuButton)).toBe(false);
    expect(menuButton.closest("a")).toBeNull();
    expect(menuButton.closest(".kern-previous-chats-card")).toContainElement(
      link,
    );
    expect(menuButton.closest(".kern-previous-chats-card")).toContainElement(
      menuButton,
    );
  });

  it("declares visible keyboard focus styles for the row link and overflow control", () => {
    expect(GLOBALS_CSS).toMatch(
      /\.kern-previous-chats-row:focus-visible\s*\{[^}]*outline:\s*2px solid var\(--kern-focus\)/,
    );
    expect(GLOBALS_CSS).toMatch(
      /\.kern-chat-overflow-trigger:focus-visible\s*\{[^}]*outline:\s*2px solid var\(--kern-focus\)/,
    );
    expect(GLOBALS_CSS).toMatch(
      /\.kern-chat-overflow-trigger\s*\{[^}]*min-width:\s*40px/,
    );
    expect(GLOBALS_CSS).toMatch(
      /\.kern-chat-overflow-trigger\s*\{[^}]*min-height:\s*40px/,
    );
    expect(GLOBALS_CSS).toMatch(
      /\.kern-chat-overflow-trigger\s*\{[^}]*background:\s*transparent/,
    );
    expect(GLOBALS_CSS).toMatch(
      /\.kern-chat-overflow-trigger\s*\{[^}]*border:\s*0/,
    );
    expect(GLOBALS_CSS).toMatch(
      /\.kern-chat-overflow-trigger:hover\s+\.kern-chat-overflow-icon[\s\S]*?transform:\s*rotate\(180deg\)/,
    );
    expect(GLOBALS_CSS).not.toMatch(
      /\.kern-chat-overflow-trigger:hover\s*\{[^}]*background:\s*color-mix/,
    );
    expect(GLOBALS_CSS).not.toMatch(
      /\.kern-previous-chats-card\s+\.kern-chat-overflow-trigger\s*\{[^}]*opacity:\s*0/,
    );
  });

  it("keeps the overflow menu from navigating when opened", async () => {
    const user = userEvent.setup();
    createConversation({
      title: "Stay put",
      messages: [{ id: "1", role: "user", content: "Stay put" }],
      draft: "",
    });

    render(<PreviousChats />);

    const menuButton = screen.getByRole("button", {
      name: "Conversation actions for Stay put",
    });
    await user.click(menuButton);

    expect(screen.getByRole("menu")).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: /^rename$/i })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: /^delete$/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Stay put/i })).toHaveAttribute(
      "href",
      expect.stringMatching(/^\/chat\//),
    );
  });

  it("renames a conversation from the overflow menu", async () => {
    const user = userEvent.setup();
    const created = createConversation({
      title: "Old title",
      messages: [{ id: "1", role: "user", content: "Old title" }],
      draft: "",
    });

    render(<PreviousChats />);

    await user.click(
      screen.getByRole("button", {
        name: "Conversation actions for Old title",
      }),
    );
    await user.click(screen.getByRole("menuitem", { name: /^rename$/i }));
    const input = await screen.findByRole("textbox", { name: /rename/i });
    await user.clear(input);
    await user.type(input, "Renamed title{Enter}");

    await waitFor(() => {
      expect(getConversation(created.id)?.title).toBe("Renamed title");
    });
    expect(screen.getByRole("link", { name: /Renamed title/i })).toBeInTheDocument();
  });

  it("deletes a conversation after ConfirmDialog confirmation", async () => {
    const user = userEvent.setup();
    createConversation({
      title: "Remove this thread",
      messages: [{ id: "1", role: "user", content: "Remove this thread" }],
      draft: "",
    });

    render(<PreviousChats />);

    await user.click(
      screen.getByRole("button", {
        name: "Conversation actions for Remove this thread",
      }),
    );
    await user.click(screen.getByRole("menuitem", { name: /^delete$/i }));
    expect(
      await screen.findByRole("heading", { name: /delete conversation/i }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^delete$/i }));

    await waitFor(() => {
      expect(listConversations()).toEqual([]);
    });
  });

  it("cancels delete without removing the conversation", async () => {
    const user = userEvent.setup();
    const created = createConversation({
      title: "Keep me",
      messages: [{ id: "1", role: "user", content: "Keep me" }],
      draft: "",
    });

    render(<PreviousChats />);

    await user.click(
      screen.getByRole("button", {
        name: "Conversation actions for Keep me",
      }),
    );
    await user.click(screen.getByRole("menuitem", { name: /^delete$/i }));
    await user.click(screen.getByRole("button", { name: /cancel/i }));

    expect(getConversation(created.id)).not.toBeNull();
  });

  it("places unread left of the title and thinking beside the title", () => {
    createConversation({
      title: "Unread thread",
      messages: [{ id: "1", role: "user", content: "Unread thread" }],
      draft: "",
      unread: true,
    });
    createConversation({
      title: "Pending thread",
      messages: [{ id: "2", role: "user", content: "Pending thread" }],
      draft: "",
      runStatus: "pending",
      requestStartedAt: Date.now(),
    });

    render(<PreviousChats />);

    const unreadLink = screen.getByRole("link", { name: /Unread thread/i });
    const unreadMain = unreadLink.querySelector(".kern-previous-chats-row-main");
    const unreadDot = unreadLink.querySelector(
      ".kern-previous-chats-status--unread",
    );
    const unreadTitle = unreadLink.querySelector(
      ".kern-previous-chats-row-title",
    );
    expect(unreadMain?.firstElementChild).toBe(unreadDot);
    expect(unreadDot?.nextElementSibling).toBe(unreadTitle);
    expect(
      unreadLink.querySelector(
        ".kern-previous-chats-row-meta .kern-previous-chats-status",
      ),
    ).toBeNull();

    const pendingLink = screen.getByRole("link", { name: /Pending thread/i });
    const pendingTitle = pendingLink.querySelector(
      ".kern-previous-chats-row-title",
    );
    const thinking = pendingLink.querySelector(
      ".kern-previous-chats-status--pending",
    );
    expect(pendingTitle?.nextElementSibling).toBe(thinking);
    expect(
      screen.getByRole("status", { name: /request in progress/i }),
    ).toBe(thinking);
    expect(
      thinking?.querySelector(".kern-thinking-mark, .kern-chat-thinking-mark"),
    ).not.toBeNull();
    expect(thinking?.querySelector(".kn-rest")).not.toBeNull();
    expect(thinking?.querySelector("style")).toBeNull();
  });
});
