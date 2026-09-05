"use client";

import {
  useEffect,
  useState,
  startTransition,
  type KeyboardEvent,
  type SubmitEvent,
} from "react";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/states/EmptyState";
import { UnavailableState } from "@/components/states/UnavailableState";
import {
  askChat,
  type AskChatOptions,
  type ChatAskResponse,
} from "@/lib/api/chat";
import { ApiError } from "@/lib/api/errors";
import { runDetailLines } from "@/lib/chat/run-details";
import {
  appendUserMessage,
  applyTurnResult,
  classifyFailure,
  historyForModel,
  type ChatMessage,
  type Citation,
  type ToolRun,
  type ToolUsed,
} from "@/lib/chat/turn";
import {
  clearChatMessages,
  loadChatMessages,
  loadRuntimeSettings,
  saveChatMessages,
} from "@/lib/runtime-settings-storage";

const SEND_ICON = (
  <svg
    className="kern-chat-send-icon"
    viewBox="0 0 24 24"
    fill="none"
    aria-hidden="true"
  >
    <path
      d="M4.5 12.5 20 4.5l-4.2 15.2-3.6-5.4-5.7-1.8Z"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinejoin="round"
    />
    <path
      d="M12.2 14.3 20 4.5"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
    />
  </svg>
);
export type ChatPanelProps = {
  apiBaseUrl: string;
  ask?: (options: AskChatOptions) => Promise<ChatAskResponse>;
};

function CitationsBlock({ citations }: { citations: Citation[] }) {
  if (citations.length === 0) {
    return null;
  }
  return (
    <details className="kern-chat-details">
      <summary>Citations ({citations.length})</summary>
      <ol className="kern-chat-list">
        {citations.map((citation, index) => (
          <li key={`${citation.source_id}-${index}`}>
            <code>{citation.source_id}</code> ({citation.source_type})
            {citation.chunk_index != null ? ` · chunk ${citation.chunk_index}` : ""}
            {citation.quote ? (
              <p className="kern-chat-quote">{citation.quote}</p>
            ) : null}
          </li>
        ))}
      </ol>
    </details>
  );
}

function ToolsUsedBlock({ tools }: { tools: ToolUsed[] }) {
  if (tools.length === 0) {
    return null;
  }
  return (
    <details className="kern-chat-details">
      <summary>Tools used ({tools.length})</summary>
      <ul className="kern-chat-list">
        {tools.map((tool) => (
          <li key={tool.tool_name}>
            <code>{tool.tool_name}</code> — {tool.result_chars} characters
          </li>
        ))}
      </ul>
    </details>
  );
}

function ToolRunBlock({ toolRun }: { toolRun: ToolRun }) {
  return (
    <div className="kern-chat-tool-run">
      {toolRun.calls.length > 0 ? (
        <>
          <p className="kern-chat-label">Tool calls</p>
          <ul className="kern-chat-list">
            {toolRun.calls.map((call) => (
              <li key={call.tool_name}>
                <code>{call.tool_name}</code> — {call.ok ? "succeeded" : "failed"}
                {call.ok && call.summary ? ` — ${call.summary}` : ""}
              </li>
            ))}
          </ul>
        </>
      ) : null}
      {toolRun.summary ? <p className="kern-chat-caption">{toolRun.summary}</p> : null}
      {toolRun.risk ? (
        <div>
          <p className="kern-chat-label">Risk</p>
          <p>
            Score {toolRun.risk.score}/100 ({toolRun.risk.level})
          </p>
          <p>{toolRun.risk.rationale}</p>
          <ul className="kern-chat-list">
            {toolRun.risk.factors.map((factor) => (
              <li key={factor.factor_id}>
                <code>{factor.factor_id}</code> (weight {factor.weight})
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {toolRun.test_cases ? (
        <div>
          <p className="kern-chat-label">
            Test cases ({toolRun.test_cases.output_style})
          </p>
          {toolRun.test_cases.cases.map((testCase) => (
            <details key={testCase.title} className="kern-chat-details">
              <summary>{testCase.title}</summary>
              <ol>
                {testCase.steps.map((step) => (
                  <li key={step}>{step}</li>
                ))}
              </ol>
              <p>
                <strong>Expected:</strong> {testCase.expected}
              </p>
            </details>
          ))}
        </div>
      ) : null}
      {toolRun.markdown ? (
        <details className="kern-chat-details">
          <summary>Markdown preview</summary>
          <pre className="kern-chat-pre">{toolRun.markdown}</pre>
          <Button
            variant="secondary"
            type="button"
            onClick={() => {
              void navigator.clipboard?.writeText(toolRun.markdown);
            }}
          >
            Copy markdown
          </Button>
        </details>
      ) : null}
    </div>
  );
}

function RunDetailsBlock({ run }: { run: ChatMessage["run"] }) {
  const lines = runDetailLines(run);
  if (lines.length === 0) {
    return null;
  }
  return (
    <details className="kern-chat-details">
      <summary>Run details</summary>
      <ul className="kern-chat-list">
        {lines.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
    </details>
  );
}

function MessageRow({ message }: { message: ChatMessage }) {
  if (message.displayOnly) {
    return (
      <article className="kern-chat-msg kern-chat-msg--error" data-role="assistant">
        <p role="alert">{message.content}</p>
        <RunDetailsBlock run={message.run} />
      </article>
    );
  }
  if (message.role === "user") {
    return (
      <article className="kern-chat-msg kern-chat-msg--user" data-role="user">
        <p>{message.content}</p>
      </article>
    );
  }
  return (
    <article className="kern-chat-msg kern-chat-msg--assistant" data-role="assistant">
      <div className="kern-chat-answer">{message.content}</div>
      <CitationsBlock citations={message.citations ?? []} />
      <ToolsUsedBlock tools={message.toolsUsed ?? []} />
      {message.toolRun ? <ToolRunBlock toolRun={message.toolRun} /> : null}
      <RunDetailsBlock run={message.run} />
    </article>
  );
}

function toPersisted(messages: ChatMessage[]) {
  return messages.map((message) => ({
    id: message.id,
    role: message.role,
    content: message.content,
    displayOnly: message.displayOnly,
    citations: message.citations,
    toolsUsed: message.toolsUsed,
    run: message.run,
    toolRun: message.toolRun,
  }));
}

function fromPersisted(raw: ReturnType<typeof loadChatMessages>): ChatMessage[] {
  return raw.map((message) => ({
    id: message.id,
    role: message.role,
    content: message.content,
    displayOnly: message.displayOnly,
    citations: (message.citations as ChatMessage["citations"]) ?? undefined,
    toolsUsed: (message.toolsUsed as ChatMessage["toolsUsed"]) ?? undefined,
    run: (message.run as ChatMessage["run"]) ?? undefined,
    toolRun: (message.toolRun as ChatMessage["toolRun"]) ?? undefined,
  }));
}

export function ChatPanel({ apiBaseUrl, ask = askChat }: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [hydrated, setHydrated] = useState(false);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [inlineError, setInlineError] = useState<string | null>(null);
  const [unavailable, setUnavailable] = useState(false);

  useEffect(() => {
    startTransition(() => {
      setMessages(fromPersisted(loadChatMessages()));
      setHydrated(true);
    });
  }, []);

  useEffect(() => {
    if (!hydrated) {
      return;
    }
    saveChatMessages(toPersisted(messages));
  }, [messages, hydrated]);

  async function handleSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const query = draft.trim();
    if (!query || sending) {
      return;
    }
    setInlineError(null);
    setUnavailable(false);
    setDraft("");
    const history = historyForModel(messages);
    const withUser = appendUserMessage(messages, query);
    setMessages(withUser);
    setSending(true);
    try {
      const stored = loadRuntimeSettings();
      const response = await ask({
        baseUrl: apiBaseUrl,
        body: {
          query,
          history,
          runtime: stored
            ? {
                provider:
                  stored.provider === "ollama" || stored.provider === "openrouter"
                    ? stored.provider
                    : null,
                model: stored.model,
                settings: stored.settings,
              }
            : null,
        },
      });
      setMessages((current) =>
        applyTurnResult(current, { kind: "success", response }),
      );
    } catch (error) {
      const apiError =
        error instanceof ApiError ? error : ApiError.generic(0);
      const failure = classifyFailure(apiError);
      if (failure.kind === "unavailable") {
        setUnavailable(true);
        setMessages((current) => applyTurnResult(current, failure));
      } else if (failure.kind === "rejected") {
        setInlineError(failure.message);
        setMessages((current) => applyTurnResult(current, failure));
      } else {
        setMessages((current) => applyTurnResult(current, failure));
      }
    } finally {
      setSending(false);
    }
  }

  function handleNewChat() {
    clearChatMessages();
    setMessages([]);
    setInlineError(null);
    setUnavailable(false);
    setDraft("");
  }

  if (unavailable && messages.length === 0) {
    return (
      <section className="kern-chat">
        <header className="kern-chat-header">
          <h1>Chat</h1>
          <Button variant="secondary" type="button" onClick={handleNewChat}>
            New chat
          </Button>
        </header>
        <div className="kern-chat-body">
          <UnavailableState
            title="Backend unavailable"
            description="Kernector could not reach the API. Check that the FastAPI server is running, then try again."
          />
        </div>
      </section>
    );
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  }

  return (
    <section className="kern-chat">
      <header className="kern-chat-header">
        <div>
          <h1>Chat</h1>
          <p className="kern-chat-lead">
            General grounded chat over ingested documents.
          </p>
        </div>
        <Button variant="secondary" type="button" onClick={handleNewChat}>
          New chat
        </Button>
      </header>

      <div className="kern-chat-body">
        {unavailable ? (
          <UnavailableState
            title="Backend unavailable"
            description="Kernector could not reach the API. Check that the FastAPI server is running, then try again."
          />
        ) : null}

        {messages.length === 0 && hydrated && !unavailable ? (
          <EmptyState
            title="Start a conversation"
            description="Ask a question grounded in your ingested documents."
          />
        ) : (
          <div className="kern-chat-thread" aria-live="polite">
            {messages.map((message) => (
              <MessageRow key={message.id} message={message} />
            ))}
            {sending ? (
              <p className="kern-chat-thinking" aria-busy="true">
                Thinking…
              </p>
            ) : null}
          </div>
        )}
      </div>

      {inlineError ? (
        <p className="kern-chat-inline-error" role="alert">
          {inlineError}
        </p>
      ) : null}

      <form className="kern-chat-composer" onSubmit={handleSubmit}>
        <div className="kern-chat-composer-bar">
          <label className="visually-hidden" htmlFor="chat-input">
            Message
          </label>
          <textarea
            id="chat-input"
            className="kern-chat-input"
            rows={1}
            placeholder="Ask about your documents…"
            value={draft}
            disabled={sending}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={handleComposerKeyDown}
          />
          <button
            type="submit"
            className="kern-chat-send"
            aria-label="Send"
            disabled={sending || !draft.trim()}
          >
            {SEND_ICON}
          </button>
        </div>
      </form>
    </section>
  );
}
