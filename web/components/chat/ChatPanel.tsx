"use client";

import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type SubmitEvent,
} from "react";
import { Button } from "@/components/ui/Button";
import { UnavailableState } from "@/components/states/UnavailableState";
import { KernectorThinkingMark } from "@/components/shell/KernectorThinkingMark";
import {
  askChat,
  type AskChatOptions,
  type ChatAskResponse,
} from "@/lib/api/chat";
import { ApiError } from "@/lib/api/errors";
import type {
  GetRuntimeSettingsOptions,
  RuntimeSettingsResponse,
} from "@/lib/api/settings";
import {
  evaluateHistoryLength,
  evaluateInputLength,
} from "@/lib/chat/input-length";
import { runDetailLines } from "@/lib/chat/run-details";
import {
  appendUserMessage,
  applyTurnResult,
  classifyFailure,
  historyForModel,
  seedIds,
  type ChatMessage,
  type Citation,
  type ToolRun,
  type ToolUsed,
} from "@/lib/chat/turn";
import {
  loadRuntimeSettings,
  type StoredChatMessage,
} from "@/lib/settings/runtime-settings-storage";
import {
  loadActiveSession,
  saveActiveSession,
  saveActiveSessionDraft,
  subscribeActiveSession,
} from "@/lib/session/active-session";
import { useRuntimeCatalog } from "@/lib/settings/use-runtime-catalog";

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

const DRAFT_SAVE_DEBOUNCE_MS = 300;

export type ChatPanelProps = {
  apiBaseUrl: string;
  ask?: (options: AskChatOptions) => Promise<ChatAskResponse>;
  loadSettings?: (
    options: GetRuntimeSettingsOptions,
  ) => Promise<RuntimeSettingsResponse>;
};

function CitationsBlock({ citations }: { citations: Citation[] }) {
  if (!Array.isArray(citations) || citations.length === 0) {
    return null;
  }
  return (
    <details className="kern-chat-details">
      <summary>Citations ({citations.length})</summary>
      <ol className="kern-chat-list">
        {citations.map((citation, index) => (
          <li key={`${citation.source_id}-${index}`}>
            <code>{citation.source_id}</code> ({citation.source_type})
            {citation.chunk_index != null
              ? ` · chunk ${citation.chunk_index}`
              : ""}
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
  if (!Array.isArray(tools) || tools.length === 0) {
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
  const calls = Array.isArray(toolRun.calls)
    ? toolRun.calls.filter(Boolean)
    : [];
  const riskFactors = Array.isArray(toolRun.risk?.factors)
    ? toolRun.risk.factors.filter(Boolean)
    : [];
  const testCases = Array.isArray(toolRun.test_cases?.cases)
    ? toolRun.test_cases.cases.filter(Boolean)
    : [];
  const summary =
    typeof toolRun.summary === "string" ? toolRun.summary : undefined;
  const markdown =
    typeof toolRun.markdown === "string" ? toolRun.markdown : undefined;
  const riskScore =
    typeof toolRun.risk?.score === "number" ? toolRun.risk.score : undefined;
  const riskLevel =
    typeof toolRun.risk?.level === "string" ? toolRun.risk.level : undefined;
  const riskRationale =
    typeof toolRun.risk?.rationale === "string"
      ? toolRun.risk.rationale
      : undefined;
  const outputStyle =
    typeof toolRun.test_cases?.output_style === "string"
      ? toolRun.test_cases.output_style
      : undefined;

  return (
    <div className="kern-chat-tool-run">
      {calls.length > 0 ? (
        <>
          <p className="kern-chat-label">Tool calls</p>
          <ul className="kern-chat-list">
            {calls.map((call) => (
              <li key={call.tool_name}>
                <code>{call.tool_name}</code> —{" "}
                {call.ok ? "succeeded" : "failed"}
                {call.ok && typeof call.summary === "string"
                  ? ` — ${call.summary}`
                  : ""}
              </li>
            ))}
          </ul>
        </>
      ) : null}
      {summary ? <p className="kern-chat-caption">{summary}</p> : null}
      {toolRun.risk ? (
        <div>
          <p className="kern-chat-label">Risk</p>
          <p>
            Score {riskScore ?? "—"}/100 ({riskLevel ?? "—"})
          </p>
          {riskRationale ? <p>{riskRationale}</p> : null}
          <ul className="kern-chat-list">
            {riskFactors.map((factor) => (
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
            Test cases{outputStyle ? ` (${outputStyle})` : ""}
          </p>
          {testCases.map((testCase) => {
            const steps = Array.isArray(testCase.steps)
              ? testCase.steps.filter(
                  (step): step is string => typeof step === "string",
                )
              : [];
            const title =
              typeof testCase.title === "string" ? testCase.title : "Case";
            const expected =
              typeof testCase.expected === "string" ? testCase.expected : "";
            return (
              <details key={title} className="kern-chat-details">
                <summary>{title}</summary>
                <ol>
                  {steps.map((step) => (
                    <li key={step}>{step}</li>
                  ))}
                </ol>
                {expected ? (
                  <p>
                    <strong>Expected:</strong> {expected}
                  </p>
                ) : null}
              </details>
            );
          })}
        </div>
      ) : null}
      {markdown ? (
        <details className="kern-chat-details">
          <summary>Markdown preview</summary>
          <pre className="kern-chat-pre">{markdown}</pre>
          <Button
            variant="secondary"
            type="button"
            onClick={() => {
              void navigator.clipboard?.writeText(markdown);
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
      <article
        className="kern-chat-msg kern-chat-msg--error"
        data-role="assistant"
      >
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
    <article
      className="kern-chat-msg kern-chat-msg--assistant"
      data-role="assistant"
    >
      <div className="kern-chat-answer">{message.content}</div>
      <CitationsBlock citations={message.citations ?? []} />
      <ToolsUsedBlock tools={message.toolsUsed ?? []} />
      {message.toolRun ? <ToolRunBlock toolRun={message.toolRun} /> : null}
      <RunDetailsBlock run={message.run} />
    </article>
  );
}

function toPersisted(messages: ChatMessage[]): StoredChatMessage[] {
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

function fromPersisted(raw: StoredChatMessage[]): ChatMessage[] {
  return raw.map((message) => ({
    id: message.id,
    role: message.role,
    content: message.content,
    displayOnly: message.displayOnly,
    citations: message.citations as ChatMessage["citations"],
    toolsUsed: message.toolsUsed as ChatMessage["toolsUsed"],
    run: message.run as ChatMessage["run"],
    toolRun: message.toolRun as ChatMessage["toolRun"],
  }));
}

export function ChatPanel({
  apiBaseUrl,
  ask = askChat,
  loadSettings,
}: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [hydrated, setHydrated] = useState(false);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [inlineError, setInlineError] = useState<string | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const {
    catalog,
    error: settingsError,
    loading: settingsLoading,
    reload: reloadSettings,
  } = useRuntimeCatalog(apiBaseUrl, loadSettings);
  const maxInputLength = catalog?.constraints.max_input_length ?? null;

  const composerTouchedRef = useRef(false);
  const sessionUpdatedAtRef = useRef(0);
  const turnGenerationRef = useRef(0);
  const skipNextPersistRef = useRef(false);
  const draftRef = useRef(draft);

  useEffect(() => {
    draftRef.current = draft;
  }, [draft]);

  useEffect(() => {
    const session = loadActiveSession();
    seedIds(session.messages);
    sessionUpdatedAtRef.current = session.updatedAt;
    setMessages((current) =>
      current.length ? current : fromPersisted(session.messages),
    );
    if (!composerTouchedRef.current) {
      setDraft(session.draft);
    }
    setHydrated(true);
  }, []);

  useEffect(() => {
    return subscribeActiveSession(() => {
      const session = loadActiveSession();
      if (session.updatedAt <= sessionUpdatedAtRef.current) {
        return;
      }
      seedIds(session.messages);
      sessionUpdatedAtRef.current = session.updatedAt;
      setMessages(fromPersisted(session.messages));
      if (!composerTouchedRef.current) {
        setDraft(session.draft);
      }
    });
  }, []);

  function adoptSessionStamp(stamp: number | null): void {
    if (stamp !== null) {
      sessionUpdatedAtRef.current = stamp;
      return;
    }
    const session = loadActiveSession();
    seedIds(session.messages);
    sessionUpdatedAtRef.current = session.updatedAt;
    skipNextPersistRef.current = true;
    setMessages(fromPersisted(session.messages));
    if (!composerTouchedRef.current) {
      setDraft(session.draft);
    }
  }

  useEffect(() => {
    if (!hydrated) {
      return;
    }
    if (skipNextPersistRef.current) {
      skipNextPersistRef.current = false;
      return;
    }
    adoptSessionStamp(
      saveActiveSession({
        draft: draftRef.current,
        messages: toPersisted(messages),
        updatedAt: sessionUpdatedAtRef.current,
      }),
    );
  }, [messages, hydrated]);

  useEffect(() => {
    if (!hydrated) {
      return;
    }
    const handle = window.setTimeout(() => {
      adoptSessionStamp(
        saveActiveSessionDraft(draft, sessionUpdatedAtRef.current),
      );
    }, DRAFT_SAVE_DEBOUNCE_MS);
    return () => window.clearTimeout(handle);
  }, [draft, hydrated]);

  useEffect(() => {
    return () => {
      if (!hydrated) {
        return;
      }
      const stamp = saveActiveSessionDraft(
        draftRef.current,
        sessionUpdatedAtRef.current,
      );
      if (stamp !== null) {
        sessionUpdatedAtRef.current = stamp;
      }
    };
  }, [hydrated]);

  const lengthFeedback =
    maxInputLength === null ? null : evaluateInputLength(draft, maxInputLength);
  const historyFeedback =
    maxInputLength === null
      ? null
      : evaluateHistoryLength(historyForModel(messages), maxInputLength);
  const overLimit = lengthFeedback?.exceeded ?? false;
  const historyBlocked = historyFeedback?.exceeded ?? false;
  const sendBlocked = overLimit || historyBlocked;
  const statusGuidance =
    lengthFeedback?.guidance ?? historyFeedback?.guidance ?? null;

  async function handleSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const query = draft.trim();
    setInlineError(null);
    if (!query || sending || sendBlocked) {
      return;
    }
    composerTouchedRef.current = true;
    const generation = turnGenerationRef.current;
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
                  stored.provider === "ollama" ||
                  stored.provider === "openrouter"
                    ? stored.provider
                    : null,
                model: stored.model,
                settings: stored.settings,
              }
            : null,
        },
      });
      if (generation !== turnGenerationRef.current) {
        return;
      }
      setMessages((current) =>
        applyTurnResult(current, { kind: "success", response }),
      );
    } catch (error) {
      if (generation !== turnGenerationRef.current) {
        return;
      }
      const apiError = error instanceof ApiError ? error : ApiError.generic(0);
      const failure = classifyFailure(apiError);
      if (failure.kind === "unavailable") {
        setUnavailable(true);
        setMessages((current) => applyTurnResult(current, failure));
      } else if (failure.kind === "rejected") {
        setInlineError(failure.message);
        setDraft(query);
        setMessages((current) => applyTurnResult(current, failure));
      } else {
        setMessages((current) => applyTurnResult(current, failure));
      }
    } finally {
      if (generation === turnGenerationRef.current) {
        setSending(false);
      }
    }
  }

  function handleNewChat() {
    turnGenerationRef.current += 1;
    composerTouchedRef.current = false;
    skipNextPersistRef.current = true;
    let stamp = saveActiveSession({
      draft: "",
      messages: [],
      updatedAt: sessionUpdatedAtRef.current,
    });
    // New chat is deliberate — retry once against the current revision so a
    // concurrent writer cannot leave someone else's transcript on screen.
    if (stamp === null) {
      stamp = saveActiveSession({
        draft: "",
        messages: [],
        updatedAt: loadActiveSession().updatedAt,
      });
    }
    if (stamp === null) {
      // Last-resort path: both clears lost a race. New chat still owns the
      // composer — clear draft rather than restoring a concurrent writer's.
      const session = loadActiveSession();
      seedIds(session.messages);
      sessionUpdatedAtRef.current = session.updatedAt;
      setMessages(fromPersisted(session.messages));
      setDraft("");
      setInlineError(null);
      setUnavailable(false);
      setSending(false);
      return;
    }
    sessionUpdatedAtRef.current = stamp;
    setMessages([]);
    setInlineError(null);
    setUnavailable(false);
    setDraft("");
    setSending(false);
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

  const isEmptyHero =
    hydrated && !unavailable && messages.length === 0 && !sending;
  const showHint = isEmptyHero && !inlineError && !draft.trim();
  // Option (a): keep New chat when transcript/unavailable, or when storage
  // still holds a concurrent writer's session (stale-session escape).
  const showNewChat =
    !hydrated ||
    unavailable ||
    messages.length > 0 ||
    loadActiveSession().messages.length > 0;
  const describedByIds = [
    showHint ? "chat-hint" : null,
    lengthFeedback || statusGuidance ? "chat-input-length" : null,
  ]
    .filter((id): id is string => id != null)
    .join(" ");

  return (
    <section className={`kern-chat${isEmptyHero ? " kern-chat--empty" : ""}`}>
      <header className="kern-chat-header">
        <div>
          <h1>Chat</h1>
          <p className="kern-chat-lead">
            General grounded chat over ingested documents.
          </p>
        </div>
        {showNewChat ? (
          <Button variant="secondary" type="button" onClick={handleNewChat}>
            New chat
          </Button>
        ) : null}
      </header>

      <div className="kern-chat-body">
        {settingsError ? (
          <div
            className="kern-settings-callout kern-settings-callout--error"
            role="alert"
          >
            <p>{settingsError}</p>
            <Button
              variant="secondary"
              type="button"
              disabled={settingsLoading}
              onClick={() => reloadSettings()}
            >
              {settingsLoading ? "Checking…" : "Retry"}
            </Button>
          </div>
        ) : null}

        {unavailable ? (
          <UnavailableState
            title="Backend unavailable"
            description="Kernector could not reach the API. Check that the FastAPI server is running, then try again."
          />
        ) : null}

        <div className="kern-chat-thread" aria-live="polite">
          {messages.map((message) => (
            <MessageRow key={message.id} message={message} />
          ))}
          {sending ? (
            <p className="kern-chat-thinking" role="status">
              <KernectorThinkingMark className="kern-chat-thinking-mark" />
              <span className="visually-hidden">Thinking…</span>
            </p>
          ) : null}
        </div>
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
            placeholder="What's on your mind?"
            value={draft}
            disabled={sending || historyBlocked}
            aria-invalid={sendBlocked || undefined}
            aria-describedby={describedByIds || undefined}
            onChange={(event) => {
              composerTouchedRef.current = true;
              setDraft(event.target.value);
            }}
            onKeyDown={handleComposerKeyDown}
          />
          <button
            type="submit"
            className="kern-chat-send"
            aria-label="Send"
            disabled={sending || !draft.trim() || sendBlocked}
          >
            {SEND_ICON}
          </button>
        </div>
        {showHint ? (
          <p id="chat-hint" className="kern-chat-hint">
            Typing here starts a new chat.
          </p>
        ) : null}
        {lengthFeedback || statusGuidance ? (
          <div id="chat-input-length" className="kern-chat-counter-block">
            {lengthFeedback ? (
              <p
                className="kern-chat-counter"
                data-exceeded={lengthFeedback.exceeded ? "true" : undefined}
              >
                {lengthFeedback.counterLabel}
              </p>
            ) : null}
            <p
              className="kern-chat-length-status"
              role="status"
              data-exceeded={statusGuidance ? "true" : undefined}
            >
              {statusGuidance ?? ""}
            </p>
          </div>
        ) : null}
      </form>
    </section>
  );
}
