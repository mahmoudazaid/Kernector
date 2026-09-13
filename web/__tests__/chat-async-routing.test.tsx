import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ChatLanding } from "@/components/chat/ChatLanding";
import { ConversationView } from "@/components/chat/ConversationView";
import { PreviousChats } from "@/components/chat/PreviousChats";
import type { ChatAskResponse } from "@/lib/api/chat";
import type { RuntimeSettingsResponse } from "@/lib/api/settings";
import { ApiError } from "@/lib/api/errors";
import { setActiveConversationId } from "@/lib/session/active-session";
import {
  createConversation,
  getConversation,
  listConversations,
  markConversationRead,
  resetConversationsSnapshotForTests,
  updateConversation,
} from "@/lib/session/conversations";
import {
  resetLiveConversationRunsForTests,
  startConversationRun,
} from "@/lib/session/conversation-runs";

const replace = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
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

const SUCCESS: ChatAskResponse = {
  answer: "Answer for A",
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

const stubSettings = async (): Promise<RuntimeSettingsResponse> => ({
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
});

describe("chat async routing (#246)", () => {
  beforeEach(() => {
    localStorage.clear();
    resetConversationsSnapshotForTests();
    resetLiveConversationRunsForTests();
    setActiveConversationId(null);
    replace.mockReset();
  });

  it("landing never shows a conversation transcript", async () => {
    createConversation({
      title: "Hidden on landing",
      messages: [
        { id: "1", role: "user", content: "Hidden on landing" },
        { id: "2", role: "assistant", content: "Secret answer" },
      ],
      draft: "",
    });

    render(<ChatLanding apiBaseUrl="http://127.0.0.1:8000" />);

    expect(await screen.findByPlaceholderText("What's on your mind!")).toBeInTheDocument();
    expect(screen.queryByText("Secret answer")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Hidden on landing/i })).toBeInTheDocument();
  });

  it("navigating to /chat during A's pending request shows only A's thinking status", async () => {
    const a = createConversation({
      title: "Thread A",
      messages: [{ id: "u1", role: "user", content: "Thread A" }],
      draft: "",
      runStatus: "pending",
      requestStartedAt: Date.now(),
    });
    createConversation({
      title: "Thread B",
      messages: [{ id: "u2", role: "user", content: "Thread B" }],
      draft: "",
      runStatus: "idle",
    });

    render(<PreviousChats />);

    expect(
      screen.getByRole("status", { name: /request in progress/i }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Thread A")).toBeInTheDocument();
    expect(screen.queryByLabelText("Unread response")).not.toBeInTheDocument();
    expect(getConversation(a.id)?.runStatus).toBe("pending");
  });

  it("A's late result never appears on the landing page or conversation B", async () => {
    const user = userEvent.setup();
    let resolveAsk: (value: ChatAskResponse) => void = () => undefined;
    const ask = vi.fn(
      () =>
        new Promise<ChatAskResponse>((resolve) => {
          resolveAsk = resolve;
        }),
    );

    // Spy ChatPanel ask by rendering landing with injected ask via ChatLanding's panel —
    // use startConversationRun directly for the late-result seam.
    const a = createConversation({
      title: "A question",
      messages: [{ id: "u1", role: "user", content: "A question" }],
      draft: "",
      runStatus: "pending",
      requestStartedAt: Date.now(),
    });
    const b = createConversation({
      title: "B thread",
      messages: [{ id: "u2", role: "user", content: "B only" }],
      draft: "",
    });

    const done = startConversationRun({
      conversationId: a.id,
      query: "A question",
      history: [],
      baseUrl: "http://127.0.0.1:8000",
      ask,
    });

    render(<ChatLanding apiBaseUrl="http://127.0.0.1:8000" />);
    expect(screen.queryByText("Answer for A")).not.toBeInTheDocument();

    resolveAsk(SUCCESS);
    await done;

    await waitFor(() => {
      expect(getConversation(a.id)?.unread).toBe(true);
    });
    expect(screen.queryByText("Answer for A")).not.toBeInTheDocument();
    expect(getConversation(b.id)?.messages).toEqual([
      { id: "u2", role: "user", content: "B only" },
    ]);

    render(
      <ConversationView
        apiBaseUrl="http://127.0.0.1:8000"
        conversationId={b.id}
      />,
    );
    expect(screen.queryByText("Answer for A")).not.toBeInTheDocument();
    expect(await screen.findByText("B only")).toBeInTheDocument();

    void user;
  });

  it("completion changes A to unread; opening A clears unread and shows the result", async () => {
    const a = createConversation({
      title: "A question",
      messages: [{ id: "u1", role: "user", content: "A question" }],
      draft: "",
      runStatus: "pending",
      requestStartedAt: Date.now(),
    });

    const ask = vi.fn().mockResolvedValue(SUCCESS);
    await startConversationRun({
      conversationId: a.id,
      query: "A question",
      history: [],
      baseUrl: "http://127.0.0.1:8000",
      ask,
    });

    expect(getConversation(a.id)?.unread).toBe(true);
    expect(getConversation(a.id)?.runStatus).toBe("idle");

    const { rerender } = render(<PreviousChats />);
    expect(screen.getByLabelText("Unread response")).toBeInTheDocument();

    markConversationRead(a.id);
    rerender(<PreviousChats />);
    expect(screen.queryByLabelText("Unread response")).not.toBeInTheDocument();

    render(
      <ConversationView
        apiBaseUrl="http://127.0.0.1:8000"
        conversationId={a.id}
      />,
    );
    expect(await screen.findByText("Answer for A")).toBeInTheDocument();
    expect(getConversation(a.id)?.unread).toBe(false);
  });

  it("same-tab store updates rerender the Chats list", async () => {
    render(<PreviousChats />);
    expect(screen.getByText("No chats yet")).toBeInTheDocument();

    createConversation({
      title: "Appears live",
      messages: [{ id: "1", role: "user", content: "Appears live" }],
      draft: "",
    });

    expect(
      await screen.findByRole("link", { name: /Appears live/i }),
    ).toBeInTheDocument();
  });

  it("failures show the failed state rather than unread", async () => {
    const a = createConversation({
      title: "Failing",
      messages: [{ id: "u1", role: "user", content: "Failing" }],
      draft: "",
      runStatus: "pending",
      requestStartedAt: Date.now(),
    });

    await startConversationRun({
      conversationId: a.id,
      query: "Failing",
      history: [],
      baseUrl: "http://127.0.0.1:8000",
      ask: async () => {
        throw new ApiError({
          status: 502,
          title: "Provider error",
          detail: "boom",
          code: "provider_error",
        });
      },
    });

    expect(getConversation(a.id)?.runStatus).toBe("failed");
    expect(getConversation(a.id)?.unread).toBe(false);

    render(<PreviousChats />);
    expect(screen.getByLabelText("Request failed")).toBeInTheDocument();
    expect(screen.queryByLabelText("Unread response")).not.toBeInTheDocument();
  });

  it("history surface rows remain clickable and keyboard-focusable", () => {
    const created = createConversation({
      title: "Focus me",
      messages: [{ id: "1", role: "user", content: "Focus me" }],
      draft: "",
      unread: true,
    });

    const { container } = render(<PreviousChats />);
    expect(container.querySelector(".kern-previous-chats-card")).not.toBeNull();
    expect(container.querySelector(".kern-previous-chats-surface")).toBeNull();
    const link = screen.getByRole("link", { name: /Focus me/i });
    expect(link).toHaveAttribute("href", `/chat/${created.id}`);
    expect(link.className).toMatch(/kern-previous-chats-row/);
    expect(screen.getByLabelText("Unread response")).toBeInTheDocument();
    expect(listConversations()).toHaveLength(1);
    void updateConversation;
    void stubSettings;
  });
});
