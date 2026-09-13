import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ChatRouteClient } from "@/components/chat/ChatRouteClient";
import type { ChatAskResponse } from "@/lib/api/chat";
import { ApiError } from "@/lib/api/errors";
import type { RuntimeSettingsResponse } from "@/lib/api/settings";
import {
  createConversation,
  deleteConversation,
  getConversation,
} from "@/lib/session/conversations";
import {
  resetLiveConversationRunsForTests,
  startConversationRun,
} from "@/lib/session/conversation-runs";

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
  answer: "ok",
  citations: [],
  tools_used: [],
  run: {
    request_id: "req-1",
    outcome: "success",
    latency_ms: 1,
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

describe("ChatRouteClient shell", () => {
  beforeEach(() => {
    localStorage.clear();
    resetLiveConversationRunsForTests();
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

    render(
      <ChatRouteClient
        apiBaseUrl="http://127.0.0.1:8000"
        loadSettings={stubSettings}
      />,
    );

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

  it("does not apply a late rejection from thread A onto thread C", async () => {
    const user = userEvent.setup();
    let rejectA: (error: unknown) => void = () => undefined;
    let resolveC: (value: ChatAskResponse) => void = () => undefined;
    let call = 0;
    const ask = vi.fn(() => {
      call += 1;
      if (call === 1) {
        return new Promise<ChatAskResponse>((_resolve, reject) => {
          rejectA = reject;
        });
      }
      return new Promise<ChatAskResponse>((resolve) => {
        resolveC = resolve;
      });
    });

    const a = createConversation({
      title: "Thread A",
      messages: [],
      draft: "",
    });
    pathname = `/chat/${a.id}`;
    const { rerender } = render(
      <ChatRouteClient
        apiBaseUrl="http://127.0.0.1:8000"
        ask={ask}
        loadSettings={stubSettings}
      />,
    );

    await user.type(await screen.findByLabelText(/message/i), "QUERY-A");
    await user.click(screen.getByRole("button", { name: /send/i }));
    expect(await screen.findByText("Thinking…")).toBeInTheDocument();

    pathname = "/chat";
    rerender(
      <ChatRouteClient
        apiBaseUrl="http://127.0.0.1:8000"
        ask={ask}
        loadSettings={stubSettings}
      />,
    );
    await waitFor(() => {
      expect(
        document.querySelector('[data-chat-mode="landing"]'),
      ).not.toBeNull();
    });

    await user.type(await screen.findByLabelText(/message/i), "QUERY-C");
    await user.click(screen.getByRole("button", { name: /send/i }));
    await waitFor(() => {
      expect(
        document.querySelector('[data-chat-mode="conversation"]'),
      ).not.toBeNull();
    });
    expect(await screen.findByText("Thinking…")).toBeInTheDocument();
    const cId = replace.mock.calls.at(-1)?.[0]?.replace("/chat/", "") as string;
    expect(getConversation(cId)?.runStatus).toBe("pending");

    rejectA(
      new ApiError({
        status: 422,
        title: "Invalid query",
        detail: "REJECTION-FROM-A",
        code: "invalid_query",
      }),
    );

    await waitFor(() => {
      expect(getConversation(a.id)).toBeNull();
    });
    expect(screen.queryByText("REJECTION-FROM-A")).not.toBeInTheDocument();
    expect(screen.getByText("Thinking…")).toBeInTheDocument();
    expect(screen.getByLabelText(/message/i)).toBeDisabled();
    expect(getConversation(cId)?.runStatus).toBe("pending");
    expect(screen.queryByDisplayValue("QUERY-A")).not.toBeInTheDocument();

    resolveC(SUCCESS);
    expect(await screen.findByText("ok")).toBeInTheDocument();
  });

  it("keeps missing-conversation feedback on /chat after close handoff", async () => {
    const user = userEvent.setup();
    const ask = vi.fn().mockResolvedValue(SUCCESS);
    const created = createConversation({
      title: "Doomed",
      messages: [],
      draft: "",
    });
    pathname = `/chat/${created.id}`;
    render(
      <ChatRouteClient
        apiBaseUrl="http://127.0.0.1:8000"
        ask={ask}
        loadSettings={stubSettings}
      />,
    );

    await user.type(await screen.findByLabelText(/message/i), "hello there");
    deleteConversation(created.id);
    await user.click(screen.getByRole("button", { name: /send/i }));

    await waitFor(() => {
      expect(
        document.querySelector('[data-chat-mode="landing"]'),
      ).not.toBeNull();
    });
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /no longer available/i,
    );
    expect(screen.getByLabelText(/message/i)).toHaveValue("hello there");
    expect(ask).not.toHaveBeenCalled();
    expect(replace).toHaveBeenCalledWith("/chat");
  });
});
