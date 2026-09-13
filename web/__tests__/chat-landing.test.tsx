import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ChatRouteClient } from "@/components/chat/ChatRouteClient";
import type { ChatAskResponse } from "@/lib/api/chat";
import type { RuntimeSettingsResponse } from "@/lib/api/settings";
import {
  createConversation,
  getConversation,
  listConversations,
} from "@/lib/session/conversations";

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

const SUCCESS: ChatAskResponse = {
  answer: "Grounded answer.",
  citations: [],
  tools_used: [],
  run: {
    request_id: "req-1",
    outcome: "success",
    latency_ms: 10,
    model: "test",
    hit_count: 0,
    citation_count: 0,
    tools: [],
  },
  tool_run: null,
};

async function stubSettings(): Promise<RuntimeSettingsResponse> {
  return {
    providers: ["openrouter"],
    default_provider: "openrouter",
    openrouter: { models: [], default_model: null },
    ollama: { default_base_url: null, default_model: null },
    model_settings: [],
    enabled_packs: [],
    constraints: {
      max_input_length: 10_000,
      max_upload_bytes: 5_242_880,
      supported_upload_suffixes: [".md", ".pdf", ".txt", ".markdown"],
    },
  };
}

describe("chat landing and conversation UX (#246)", () => {
  beforeEach(() => {
    localStorage.clear();
    replace.mockReset();
    pathname = "/chat";
  });

  it("shows a full-width landing with composer above Chats and no New chat or sidebar", async () => {
    createConversation({
      title: "Saved thread",
      messages: [{ id: "1", role: "user", content: "Saved thread" }],
      draft: "",
    });

    const { container } = render(
      <ChatRouteClient
        apiBaseUrl="http://127.0.0.1:8000"
        loadSettings={stubSettings}
      />,
    );

    expect(
      await screen.findByPlaceholderText("What's on your mind!"),
    ).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Chats" })).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: "Chats" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Saved thread/i })).toHaveAttribute(
      "href",
      expect.stringMatching(/^\/chat\//),
    );

    expect(screen.queryByRole("link", { name: /new chat/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /new chat/i })).not.toBeInTheDocument();
    expect(container.querySelector(".kern-chat-layout")).toBeNull();
    expect(container.querySelector("aside.kern-chat-history")).toBeNull();
    expect(container.querySelector(".kern-chat-landing")).not.toBeNull();

    const composer = screen.getByPlaceholderText("What's on your mind!");
    const chatsHeading = screen.getByRole("heading", {
      level: 2,
      name: "Chats",
    });
    expect(
      Boolean(
        composer.compareDocumentPosition(chatsHeading) &
          Node.DOCUMENT_POSITION_FOLLOWING,
      ),
    ).toBe(true);
  });

  it("creates a conversation and routes to /chat/{id} when the landing composer is submitted", async () => {
    const user = userEvent.setup();
    let resolveAsk: (value: ChatAskResponse) => void = () => undefined;
    const ask = vi.fn(
      () =>
        new Promise<ChatAskResponse>((resolve) => {
          resolveAsk = resolve;
        }),
    );

    const { ChatPanel } = await import("@/components/chat/ChatPanel");
    const { PreviousChats } = await import("@/components/chat/PreviousChats");

    render(
      <div className="kern-chat-landing">
        <ChatPanel
          apiBaseUrl="http://127.0.0.1:8000"
          conversationId={null}
          variant="landing"
          ask={ask}
          loadSettings={stubSettings}
          onConversationCreated={(id) => replace(`/chat/${id}`)}
        />
        <PreviousChats />
      </div>,
    );

    await user.type(await screen.findByLabelText(/message/i), "First question");
    await user.click(screen.getByRole("button", { name: /send/i }));

    await waitFor(() => {
      expect(replace).toHaveBeenCalledTimes(1);
    });
    const path = replace.mock.calls[0][0] as string;
    expect(path).toMatch(/^\/chat\/.+/);
    const id = path.replace("/chat/", "");
    expect(getConversation(id)?.messages.some((m) => m.role === "user")).toBe(
      true,
    );
    expect(getConversation(id)?.runStatus).toBe("pending");
    expect(document.querySelector('[data-role="user"]')).toBeNull();
    expect(screen.queryByText("Thinking…")).not.toBeInTheDocument();

    resolveAsk(SUCCESS);
    await waitFor(() => {
      expect(
        getConversation(id)?.messages.some((m) => m.role === "assistant"),
      ).toBe(true);
    });
    expect(screen.queryByText("Grounded answer.")).not.toBeInTheDocument();
    expect(listConversations().length).toBeGreaterThanOrEqual(1);
  });

  it("opens a previous chat via its row without leaving Chats visible", async () => {
    const user = userEvent.setup();
    const created = createConversation({
      title: "Open me",
      messages: [{ id: "1", role: "user", content: "Open me" }],
      draft: "",
    });

    render(
      <ChatRouteClient
        apiBaseUrl="http://127.0.0.1:8000"
        loadSettings={stubSettings}
      />,
    );

    await user.click(screen.getByRole("link", { name: /Open me/i }));

    expect(
      document.querySelector('[data-chat-mode="conversation"]'),
    ).not.toBeNull();
    expect(screen.queryByRole("region", { name: "Chats" })).not.toBeInTheDocument();
    expect(replace).toHaveBeenCalledWith(`/chat/${created.id}`);
    expect(await screen.findByText("Open me")).toBeInTheDocument();
  });

  it("shows the transcript on /chat/{id} without Chats or New chat", async () => {
    const created = createConversation({
      title: "Thread title",
      messages: [
        { id: "1", role: "user", content: "prior turn" },
        { id: "2", role: "assistant", content: "prior answer" },
      ],
      draft: "",
    });
    pathname = `/chat/${created.id}`;

    const { container } = render(
      <ChatRouteClient
        apiBaseUrl="http://127.0.0.1:8000"
        loadSettings={stubSettings}
      />,
    );

    expect(await screen.findByText("prior turn")).toBeInTheDocument();
    expect(screen.getByText("prior answer")).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText("What's on your mind!"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { level: 2, name: "Chats" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Chats" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /new chat/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /new chat/i })).not.toBeInTheDocument();
    expect(container.querySelector(".kern-chat-landing")).toBeNull();
    expect(container.querySelector(".kern-chat-conversation")).not.toBeNull();
    expect(container.querySelector(".kern-chat-layout")).toBeNull();
  });
});
