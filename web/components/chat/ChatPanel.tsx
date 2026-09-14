"use client";

import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type SubmitEvent,
} from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/Button";
import { UnavailableState } from "@/components/states/UnavailableState";
import { KernectorThinkingMark } from "@/components/shell/KernectorThinkingMark";
import {
  ChatTestDesignAttach,
  type ChatTestDesignAttachProps,
} from "@/components/chat/ChatTestDesignAttach";
import {
  askChat,
  type AskChatOptions,
  type ChatAskResponse,
} from "@/lib/api/chat";
import { createTestDesignDraft } from "@/lib/api/test-design";
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
  softwareDeliveryPackEnabled,
  type TestDesignHandoff,
} from "@/lib/chat/test-design-handoff";
import {
  appendUserMessage,
  historyForModel,
  seedIds,
  type ChatMessage,
  type ChatWorkflowAction,
  type Citation,
  type ToolRun,
  type ToolUsed,
} from "@/lib/chat/turn";
import {
  loadRuntimeSettings,
  type StoredChatMessage,
} from "@/lib/settings/runtime-settings-storage";
import { setActiveConversationId } from "@/lib/session/active-session";
import {
  createConversation,
  deleteConversation,
  getConversation,
  migrateLegacyTranscripts,
  subscribeConversations,
  titleFromMessages,
  updateConversation,
} from "@/lib/session/conversations";
import { startConversationRun } from "@/lib/session/conversation-runs";
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
  /** Bound conversation; `null`/`undefined` = empty `/chat` draft. */
  conversationId?: string | null;
  /**
   * `landing` — empty composer only (never shows a transcript).
   * `conversation` — bound thread transcript + composer.
   */
  variant?: "landing" | "conversation";
  /** Called after the first turn creates a conversation on `/chat`. */
  onConversationCreated?: (id: string) => void;
  /** Called when a brand-new conversation is discarded (e.g. rejected query). */
  onConversationClosed?: () => void;
  ask?: (options: AskChatOptions) => Promise<ChatAskResponse>;
  loadSettings?: (
    options: GetRuntimeSettingsOptions,
  ) => Promise<RuntimeSettingsResponse>;
  /** Optional documents loader for the Test Design attach control. */
  listDocuments?: ChatTestDesignAttachProps["listDocs"];
};

type CloseHandoffNotice = {
  draft: string;
  message: string;
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

function MessageRow({
  message,
  apiBaseUrl,
  conversationId,
}: {
  message: ChatMessage;
  apiBaseUrl: string;
  conversationId: string | null;
}) {
  const router = useRouter();
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);

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

  async function handleStartWorkflow(action: ChatWorkflowAction) {
    if (
      action.kind !== "start_workflow" ||
      action.workflow_id !== "software-delivery.test-design" ||
      !action.source_reference ||
      !action.ticket_identifier ||
      !conversationId
    ) {
      return;
    }
    setStarting(true);
    setStartError(null);
    try {
      const draft = await createTestDesignDraft({
        baseUrl: apiBaseUrl,
        body: {
          conversation_id: conversationId,
          source_reference: action.source_reference,
          ticket_identifier: action.ticket_identifier,
        },
      });
      await router.push(`/test-design/${encodeURIComponent(draft.draft_id)}`);
    } catch (caught) {
      if (caught instanceof ApiError) {
        setStartError(caught.detail || "Could not start Test Design. Try again.");
      } else {
        setStartError("Could not start Test Design. Try again.");
      }
      setStarting(false);
    }
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
      {message.action?.kind === "start_workflow" &&
      message.action.workflow_id === "software-delivery.test-design" ? (
        <div className="kern-chat-action">
          <Button
            type="button"
            disabled={starting || !conversationId}
            onClick={() => {
              void handleStartWorkflow(message.action!);
            }}
          >
            {starting ? "Starting…" : message.action.label}
          </Button>
          {startError ? <p role="alert">{startError}</p> : null}
        </div>
      ) : null}
      {message.action?.kind === "open_workflow" && message.action.draft_id ? (
        <div className="kern-chat-action">
          <Button
            type="button"
            onClick={() => {
              router.push(
                `/test-design/${encodeURIComponent(message.action!.draft_id!)}`,
              );
            }}
          >
            {message.action.label}
          </Button>
        </div>
      ) : null}
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
    action: message.action,
  }));
}

function fromPersisted(messages: StoredChatMessage[]): ChatMessage[] {
  return messages.map((message) => ({
    id: message.id,
    role: message.role,
    content: message.content,
    displayOnly: message.displayOnly,
    citations: message.citations as ChatMessage["citations"],
    toolsUsed: message.toolsUsed as ChatMessage["toolsUsed"],
    run: message.run as ChatMessage["run"],
    toolRun: message.toolRun as ChatMessage["toolRun"],
    action: message.action as ChatMessage["action"],
  }));
}

type ConversationUiState = {
  boundId: string | null;
  messages: ChatMessage[];
  draft: string;
  sending: boolean;
  hydrated: boolean;
};

/** First-paint state — never reads localStorage (SSR/hydration safe). */
function mountConversationUiState(
  conversationId: string | null,
  isLanding: boolean,
): ConversationUiState {
  if (isLanding) {
    return {
      boundId: null,
      messages: [],
      draft: "",
      sending: false,
      hydrated: true,
    };
  }
  return {
    boundId: conversationId,
    messages: [],
    draft: "",
    sending: false,
    hydrated: false,
  };
}

/** Client-only re-seed when the same ChatPanel instance changes route. */
function readConversationUiState(
  conversationId: string | null,
  isLanding: boolean,
): ConversationUiState {
  if (isLanding) {
    return {
      boundId: null,
      messages: [],
      draft: "",
      sending: false,
      hydrated: true,
    };
  }
  if (!conversationId) {
    return {
      boundId: null,
      messages: [],
      draft: "",
      sending: false,
      hydrated: true,
    };
  }
  const conversation = getConversation(conversationId);
  if (!conversation) {
    return {
      boundId: conversationId,
      messages: [],
      draft: "",
      sending: false,
      hydrated: true,
    };
  }
  seedIds(conversation.messages);
  return {
    boundId: conversationId,
    messages: fromPersisted(conversation.messages),
    draft: conversation.draft,
    sending: conversation.runStatus === "pending",
    hydrated: true,
  };
}

export function ChatPanel({
  apiBaseUrl,
  conversationId = null,
  variant = conversationId ? "conversation" : "landing",
  onConversationCreated,
  onConversationClosed,
  ask = askChat,
  loadSettings,
  listDocuments,
}: ChatPanelProps) {
  const isLanding = variant === "landing";
  const bootRef = useRef<ConversationUiState | null>(null);
  if (bootRef.current === null) {
    bootRef.current = mountConversationUiState(conversationId, isLanding);
  }
  const boot = bootRef.current;
  const [boundId, setBoundId] = useState<string | null>(boot.boundId);
  const [messages, setMessages] = useState<ChatMessage[]>(boot.messages);
  const [hydrated, setHydrated] = useState(boot.hydrated);
  const [draft, setDraft] = useState(boot.draft);
  const [sending, setSending] = useState(boot.sending);
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
  const skipNextPersistRef = useRef(false);
  const draftRef = useRef(draft);
  const boundIdRef = useRef(boundId);
  const onCreatedRef = useRef(onConversationCreated);
  const onClosedRef = useRef(onConversationClosed);
  /** Survives close→landing so draft/error are not wiped by route sync. */
  const closeHandoffRef = useRef<CloseHandoffNotice | null>(null);
  const testDesignHandoffRef = useRef<TestDesignHandoff | null>(null);
  const onTestDesignHandoffChange = useRef(
    (handoff: TestDesignHandoff | null) => {
      testDesignHandoffRef.current = handoff;
    },
  ).current;
  const showTestDesignAttach = softwareDeliveryPackEnabled(
    catalog?.enabled_packs,
  );
  const routeKey = isLanding ? "landing" : (conversationId ?? "none");
  const [routeStateKey, setRouteStateKey] = useState(routeKey);
  if (routeKey !== routeStateKey) {
    // Keep transcript/pending in sync on the same ChatPanel instance when the
    // layout shell navigates `/chat` ↔ `/chat/[id]` without remounting.
    const next = readConversationUiState(conversationId, isLanding);
    const handoff = isLanding ? closeHandoffRef.current : null;
    if (handoff) {
      closeHandoffRef.current = null;
    }
    setRouteStateKey(routeKey);
    setBoundId(next.boundId);
    setMessages(next.messages);
    setSending(next.sending);
    setHydrated(next.hydrated);
    setUnavailable(false);
    if (handoff) {
      setDraft(handoff.draft);
      setInlineError(handoff.message);
      composerTouchedRef.current = true;
    } else {
      setDraft(next.draft);
      setInlineError(null);
      composerTouchedRef.current = false;
    }
  }

  useEffect(() => {
    draftRef.current = draft;
  }, [draft]);

  useEffect(() => {
    boundIdRef.current = boundId;
  }, [boundId]);

  useEffect(() => {
    onCreatedRef.current = onConversationCreated;
  }, [onConversationCreated]);

  useEffect(() => {
    onClosedRef.current = onConversationClosed;
  }, [onConversationClosed]);

  useEffect(() => {
    if (isLanding) {
      // Landing never hydrates a transcript. Legacy migrate may still create
      // a conversation and navigate via onConversationCreated.
      const migrated = migrateLegacyTranscripts();
      if (migrated.migrated && migrated.conversationId) {
        setActiveConversationId(migrated.conversationId);
        onCreatedRef.current?.(migrated.conversationId);
      }
      setBoundId(null);
      setMessages([]);
      setHydrated(true);
      return;
    }

    const migrated = migrateLegacyTranscripts();
    if (migrated.migrated && migrated.conversationId && !conversationId) {
      setActiveConversationId(migrated.conversationId);
      onCreatedRef.current?.(migrated.conversationId);
      setBoundId(migrated.conversationId);
      const conversation = getConversation(migrated.conversationId);
      if (conversation) {
        seedIds(conversation.messages);
        setMessages(fromPersisted(conversation.messages));
        setSending(conversation.runStatus === "pending");
        if (!composerTouchedRef.current) {
          setDraft(conversation.draft);
        }
      }
      setHydrated(true);
      return;
    }

    if (hydrated && conversationId && conversationId === boundIdRef.current) {
      setActiveConversationId(conversationId);
      return;
    }

    setBoundId(conversationId);
    if (conversationId) {
      setActiveConversationId(conversationId);
      const conversation = getConversation(conversationId);
      if (conversation) {
        seedIds(conversation.messages);
        skipNextPersistRef.current = true;
        setMessages(fromPersisted(conversation.messages));
        setSending(conversation.runStatus === "pending");
        if (!composerTouchedRef.current) {
          setDraft(conversation.draft);
        }
      } else {
        setMessages([]);
        setSending(false);
        if (!composerTouchedRef.current) {
          setDraft("");
        }
      }
    } else {
      setActiveConversationId(null);
      setMessages([]);
      setSending(false);
      if (!composerTouchedRef.current) {
        setDraft("");
      }
    }
    setHydrated(true);
  }, [conversationId, hydrated, isLanding]);

  useEffect(() => {
    if (isLanding) {
      return;
    }
    return subscribeConversations(() => {
      const id = boundIdRef.current;
      if (!id) {
        return;
      }
      const conversation = getConversation(id);
      if (!conversation) {
        setMessages([]);
        setSending(false);
        if (!composerTouchedRef.current) {
          setDraft("");
        }
        return;
      }
      seedIds(conversation.messages);
      skipNextPersistRef.current = true;
      setMessages(fromPersisted(conversation.messages));
      setSending(conversation.runStatus === "pending");
      if (!composerTouchedRef.current) {
        setDraft(conversation.draft);
      }
    });
  }, [isLanding]);

  function persistBound(
    id: string,
    nextMessages: ChatMessage[],
    nextDraft: string,
  ): void {
    updateConversation(id, {
      messages: toPersisted(nextMessages),
      draft: nextDraft,
    });
  }

  useEffect(() => {
    if (isLanding || !hydrated || !boundId) {
      return;
    }
    if (skipNextPersistRef.current) {
      skipNextPersistRef.current = false;
      return;
    }
    persistBound(boundId, messages, draftRef.current);
  }, [messages, hydrated, boundId, isLanding]);

  useEffect(() => {
    if (isLanding || !hydrated || !boundId) {
      return;
    }
    const handle = window.setTimeout(() => {
      const conversation = getConversation(boundId);
      if (!conversation) {
        return;
      }
      updateConversation(
        boundId,
        {
          messages: conversation.messages,
          draft,
        },
        { touchUpdatedAt: false },
      );
    }, DRAFT_SAVE_DEBOUNCE_MS);
    return () => window.clearTimeout(handle);
  }, [draft, hydrated, boundId, isLanding]);

  useEffect(() => {
    return () => {
      if (isLanding || !hydrated || !boundIdRef.current) {
        return;
      }
      const conversation = getConversation(boundIdRef.current);
      if (!conversation) {
        return;
      }
      updateConversation(
        boundIdRef.current,
        {
          messages: conversation.messages,
          draft: draftRef.current,
        },
        { touchUpdatedAt: false },
      );
    };
  }, [hydrated, isLanding]);

  const lengthFeedback =
    maxInputLength === null ? null : evaluateInputLength(draft, maxInputLength);
  const historyFeedback =
    maxInputLength === null || isLanding
      ? null
      : evaluateHistoryLength(historyForModel(messages), maxInputLength);
  const overLimit = lengthFeedback?.exceeded ?? false;
  const historyBlocked = historyFeedback?.exceeded ?? false;
  const sendBlocked = overLimit || historyBlocked;
  const statusGuidance =
    lengthFeedback?.guidance ?? historyFeedback?.guidance ?? null;

  function runtimeFromSettings(): AskChatOptions["body"]["runtime"] {
    const stored = loadRuntimeSettings();
    if (!stored) {
      return null;
    }
    const provider =
      stored.provider === "ollama" || stored.provider === "openrouter"
        ? stored.provider
        : null;
    return {
      provider,
      model: stored.model,
      settings: stored.settings,
    };
  }

  async function handleSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const query = draft.trim();
    setInlineError(null);
    if (!query || sending || sendBlocked) {
      return;
    }
    composerTouchedRef.current = true;
    setUnavailable(false);
    setDraft("");
    const handoff = testDesignHandoffRef.current;

    if (isLanding) {
      const withUser = appendUserMessage([], query);
      const created = createConversation({
        title: titleFromMessages(toPersisted(withUser)),
        messages: toPersisted(withUser),
        draft: "",
        runStatus: "pending",
        requestStartedAt: Date.now(),
        unread: false,
      });
      setActiveConversationId(created.id);
      // Register the live run before navigation/shell effects so
      // interruptStalePendingFromCoordinator does not clear pending.
      const runPromise = startConversationRun({
        conversationId: created.id,
        query,
        history: [],
        baseUrl: apiBaseUrl,
        ask,
        runtime: runtimeFromSettings(),
        source_reference: handoff?.source_reference ?? null,
        ticket_identifier: handoff?.ticket_identifier ?? null,
      });
      onCreatedRef.current?.(created.id);
      const result = await runPromise;
      await applyConversationRunResult(created.id, query, result);
      return;
    }

    const history = historyForModel(messages);
    const withUser = appendUserMessage(messages, query);
    setMessages(withUser);
    const id = boundIdRef.current ?? conversationId;
    if (!id) {
      setDraft(query);
      setMessages(messages);
      return;
    }
    updateConversation(id, {
      messages: toPersisted(withUser),
      draft: "",
      runStatus: "pending",
      requestStartedAt: Date.now(),
      unread: false,
    });
    setSending(true);
    const result = await startConversationRun({
      conversationId: id,
      query,
      history,
      baseUrl: apiBaseUrl,
      ask,
      runtime: runtimeFromSettings(),
      source_reference: handoff?.source_reference ?? null,
      ticket_identifier: handoff?.ticket_identifier ?? null,
    });
    await applyConversationRunResult(id, query, result);
  }

  async function applyConversationRunResult(
    id: string,
    query: string,
    result: Awaited<ReturnType<typeof startConversationRun>>,
  ): Promise<void> {
    if (result.kind === "rejected") {
      const conversation = getConversation(id);
      const discard = !conversation || conversation.messages.length === 0;
      if (discard && conversation) {
        deleteConversation(id);
      }
      // Store already recorded the outcome on `id`; never mutate another thread's UI.
      if (boundIdRef.current !== id) {
        // Landing first-turn reject before bind: restore query on the empty
        // composer. Never paint another thread's rejection onto the open one.
        if (discard && boundIdRef.current === null) {
          setSending(false);
          setInlineError(result.message);
          setDraft(query);
          setMessages([]);
          closeHandoffRef.current = { draft: query, message: result.message };
          onClosedRef.current?.();
        }
        return;
      }
      setSending(false);
      setInlineError(result.message);
      setDraft(query);
      if (discard) {
        setMessages([]);
        closeHandoffRef.current = { draft: query, message: result.message };
        onClosedRef.current?.();
      }
      return;
    }

    if (boundIdRef.current !== id) {
      return;
    }

    if (result.kind === "missing") {
      setSending(false);
      setMessages([]);
      setDraft(query);
      const message = "This conversation is no longer available.";
      setInlineError(message);
      closeHandoffRef.current = { draft: query, message };
      onClosedRef.current?.();
    } else if (result.kind === "unavailable") {
      setSending(false);
      setUnavailable(true);
    } else if (result.kind === "failed") {
      setSending(false);
    }
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  }

  // Empty-hero (centered composer) is landing-only. Conversation routes always
  // use the main full-height layout: transcript scrolls, composer pinned.
  const isEmptyHero = isLanding;
  const describedByIds =
    lengthFeedback || statusGuidance ? "chat-input-length" : "";

  if (unavailable && messages.length === 0) {
    return (
      <section className="kern-chat">
        <header className="kern-chat-header">
          <h1>Chat</h1>
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

  return (
    <section className={`kern-chat${isEmptyHero ? " kern-chat--empty" : ""}`}>
      <header className="kern-chat-header">
        <h1>Chat</h1>
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
            <MessageRow
              key={message.id}
              message={message}
              apiBaseUrl={apiBaseUrl}
              conversationId={boundId}
            />
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

      {showTestDesignAttach ? (
        <ChatTestDesignAttach
          apiBaseUrl={apiBaseUrl}
          disabled={sending || historyBlocked}
          listDocs={listDocuments}
          onHandoffChange={onTestDesignHandoffChange}
        />
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
            placeholder="What's on your mind!"
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
