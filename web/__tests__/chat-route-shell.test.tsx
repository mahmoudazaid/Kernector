import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ChatRouteClient } from "@/components/chat/ChatRouteClient";
import { createConversation } from "@/lib/session/conversations";
import { startConversationRun } from "@/lib/session/conversation-runs";

const replace = vi.fn();
let pathname = "/chat";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
  usePathname: () => pathname,
}));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    onClick,
    ...props
  }: {
    href: string;
    children: React.ReactNode;
    onClick?: (event: React.MouseEvent) => void;
    [key: string]: unknown;
  }) => (
    <a
      href={href}
      {...props}
      onClick={(event) => {
        onClick?.(event);
      }}
    >
      {children}
    </a>
  ),
}));

describe("ChatRouteClient shell", () => {
  beforeEach(() => {
    localStorage.clear();
    replace.mockReset();
    pathname = "/chat";
  });

  it("opens a conversation immediately without leaving Chats visible", async () => {
    const user = userEvent.setup();
    const created = createConversation({
      title: "First ask",
      messages: [{ id: "u1", role: "user", content: "First ask" }],
      draft: "",
      runStatus: "pending",
      requestStartedAt: Date.now(),
    });
    void startConversationRun({
      conversationId: created.id,
      query: "First ask",
      history: [],
      baseUrl: "http://127.0.0.1:8000",
      ask: () =>
        new Promise(() => {
          /* keep pending */
        }),
    });

    render(<ChatRouteClient apiBaseUrl="http://127.0.0.1:8000" />);

    expect(document.querySelector('[data-chat-mode="landing"]')).not.toBeNull();
    expect(screen.getByRole("region", { name: "Chats" })).toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: /First ask/i }));

    expect(
      document.querySelector('[data-chat-mode="conversation"]'),
    ).not.toBeNull();
    expect(screen.queryByRole("region", { name: "Chats" })).not.toBeInTheDocument();
    expect(replace).toHaveBeenCalledWith(`/chat/${created.id}`);

    await waitFor(() => {
      const userBubble = document.querySelector('[data-role="user"]');
      expect(userBubble).toHaveTextContent("First ask");
    });
    expect(screen.getByText("Thinking…")).toBeInTheDocument();

    const chat = document.querySelector(".kern-chat-conversation .kern-chat");
    expect(chat).not.toBeNull();
    expect(chat).not.toHaveClass("kern-chat--empty");
  });
});
