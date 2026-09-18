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
import { SoftSelect } from "@/components/ui/SoftSelect";
import { UnavailableState } from "@/components/states/UnavailableState";
import { KernectorThinkingMark } from "@/components/shell/KernectorThinkingMark";
import {
  askChat,
  clearChatCheckpointBestEffort,
  type AskChatOptions,
  type ChatAskResponse,
} from "@/lib/api/chat";
import { ToolApprovalCard, ExportDestinationRequiredPanel } from "@/components/chat/ToolApprovalCard";
import type { ApprovalResolution } from "@/components/chat/ToolApprovalCard";
import { MessageFeedbackControls } from "@/components/chat/MessageFeedbackControls";
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
  newConversationId,
  subscribeConversations,
  titleFromMessages,
  updateConversation,
  type ConversationResponseStyle,
} from "@/lib/session/conversations";
import { startConversationRun } from "@/lib/session/conversation-runs";
import { useRuntimeCatalog } from "@/lib/settings/use-runtime-catalog";

const RESPONSE_STYLE_OPTIONS = [
  "Default",
  "Formal",
  "Friendly",
  "Concise",
] as const;

const STYLE_ICON = (
  <svg
    className="kern-chat-style-icon"
    viewBox="0 0 24 24"
    fill="none"
    aria-hidden="true"
  >
    <path
      d="M5 6.5h9.5a3.5 3.5 0 0 1 0 7H12l-3.5 3.5V13.5H5A3.5 3.5 0 0 1 5 6.5Z"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinejoin="round"
    />
    <path
      d="M14 11.5h5a2.5 2.5 0 0 1 0 5h-1.2L15.5 19v-2.5H14a2.5 2.5 0 0 1 0-5Z"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinejoin="round"
    />
  </svg>
);

function styleLabel(value: ConversationResponseStyle): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function parseStyleLabel(label: string): ConversationResponseStyle {
  const lower = label.trim().toLowerCase();
  if (
    lower === "formal" ||
    lower === "friendly" ||
    lower === "concise" ||
    lower === "default"
  ) {
    return lower;
  }
  return "default";
}

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

function ToolRunBlock({
  toolRun,
  answerContent,
}: {
  toolRun: ToolRun;
  answerContent?: string;
}) {
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
  const showSummary =
    summary !== undefined &&
    summary.trim() !== "" &&
    summary.trim() !== (answerContent ?? "").trim();
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
  const hasBody =
    calls.length > 0 ||
    showSummary ||
    Boolean(toolRun.risk) ||
    Boolean(toolRun.test_cases) ||
    Boolean(markdown);
  if (!hasBody) {
    return null;
  }

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
      {showSummary ? <p className="kern-chat-caption">{summary}</p> : null}
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
  testDesignHref,
  onTestDesignStarted,
  onApprovalResolved,
  onFeedbackChanged,
}: {
  message: ChatMessage;
  apiBaseUrl: string;
  conversationId: string | null;
  testDesignHref?: string | null;
  onTestDesignStarted: (messageId: string, draftId: string) => void;
  onApprovalResolved: (
    messageId: string,
    result: {
      answer: string;
      cancelled: boolean;
      resolution: ApprovalResolution;
    },
  ) => void;
  onFeedbackChanged: (
    messageId: string,
    rating: "positive" | "negative" | null,
  ) => void;
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
      !action.source_locator ||
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
          source_locator: action.source_locator,
        },
      });
      // Persist open_workflow before navigation so returning to chat resumes
      // the same draft instead of offering Start again.
      onTestDesignStarted(message.id, draft.draft_id);
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

  const destinationRequired =
    message.toolRun?.export_destination_required === true;

  return (
    <article className="kern-chat-turn" data-role="assistant">
      <div className="kern-chat-msg kern-chat-msg--assistant">
        <div className="kern-chat-answer">{message.content}</div>
        {message.run?.request_id ? (
          <MessageFeedbackControls
            baseUrl={apiBaseUrl}
            requestId={message.run.request_id}
            conversationId={conversationId}
            clientMessageId={message.id}
            initialRating={message.feedbackRating ?? null}
            onRatingChange={(rating) => {
              onFeedbackChanged(message.id, rating);
            }}
          />
        ) : null}
        <CitationsBlock citations={message.citations ?? []} />
        <ToolsUsedBlock tools={message.toolsUsed ?? []} />
        {message.toolRun && !destinationRequired ? (
          <ToolRunBlock
            toolRun={message.toolRun}
            answerContent={message.content}
          />
        ) : null}
        <RunDetailsBlock run={message.run} />
      </div>
      {destinationRequired ? (
        <ExportDestinationRequiredPanel
          testDesignHref={testDesignHref ?? null}
          apiBaseUrl={apiBaseUrl}
          conversationId={conversationId}
        />
      ) : null}
      {message.pendingApproval && conversationId ? (
        <ToolApprovalCard
          baseUrl={apiBaseUrl}
          conversationId={conversationId}
          pending={message.pendingApproval}
          resolution={message.approvalResolution}
          onResolved={(result) => {
            onApprovalResolved(message.id, result);
          }}
        />
      ) : null}
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
              void router.push(
                `/test-design/${encodeURIComponent(message.action!.draft_id!)}`,
              );
            }}
          >
            {message.action.label || OPEN_TEST_DESIGN_LABEL}
          </Button>
        </div>
      ) : null}
    </article>
  );
}

const OPEN_TEST_DESIGN_LABEL = "Open Test Design";
const OPEN_TEST_DESIGN_ANSWER =
  "Your Test Design draft is ready. Use Open Test Design to continue coverage planning.";

function promoteStartActionToOpen(
  action: ChatWorkflowAction,
  draftId: string,
): ChatWorkflowAction {
  return {
    kind: "open_workflow",
    workflow_id: action.workflow_id,
    label: OPEN_TEST_DESIGN_LABEL,
    draft_id: draftId,
    source_locator: action.source_locator ?? null,
  };
}

function latestTestDesignHref(
  messages: readonly ChatMessage[],
): string | null {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const action = messages[index]?.action;
    if (
      action?.kind === "open_workflow" &&
      action.workflow_id === "software-delivery.test-design" &&
      typeof action.draft_id === "string" &&
      action.draft_id.trim()
    ) {
      return `/test-design/${encodeURIComponent(action.draft_id)}`;
    }
  }
  return null;
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
    pendingApproval: message.pendingApproval,
    approvalResolution: message.approvalResolution,
    feedbackRating: message.feedbackRating,
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
    pendingApproval: message.pendingApproval as ChatMessage["pendingApproval"],
    approvalResolution:
      message.approvalResolution as ChatMessage["approvalResolution"],
    feedbackRating: message.feedbackRating as ChatMessage["feedbackRating"],
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
  const [responseStyle, setResponseStyle] =
    useState<ConversationResponseStyle>("default");
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
    setResponseStyle(
      isLanding || !conversationId
        ? "default"
        : (getConversation(conversationId)?.responseStyle ?? "default"),
    );
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
        setResponseStyle(conversation.responseStyle);
        if (!composerTouchedRef.current) {
          setDraft(conversation.draft);
        }
      } else {
        setMessages([]);
        setSending(false);
        setResponseStyle("default");
        if (!composerTouchedRef.current) {
          setDraft("");
        }
      }
    } else {
      setActiveConversationId(null);
      setMessages([]);
      setSending(false);
      setResponseStyle("default");
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
        setResponseStyle("default");
        if (!composerTouchedRef.current) {
          setDraft("");
        }
        return;
      }
      seedIds(conversation.messages);
      skipNextPersistRef.current = true;
      setMessages(fromPersisted(conversation.messages));
      setSending(conversation.runStatus === "pending");
      setResponseStyle(conversation.responseStyle);
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

  function handleTestDesignStarted(messageId: string, draftId: string): void {
    setMessages((current) => {
      const next = current.map((message) => {
        if (message.id !== messageId || message.action?.kind !== "start_workflow") {
          return message;
        }
        return {
          ...message,
          content: OPEN_TEST_DESIGN_ANSWER,
          action: promoteStartActionToOpen(message.action, draftId),
        };
      });
      if (boundIdRef.current) {
        // Write through immediately — navigation may unmount before the
        // messages effect runs.
        persistBound(boundIdRef.current, next, draftRef.current);
      }
      return next;
    });
  }

  function handleApprovalResolved(
    messageId: string,
    result: {
      answer: string;
      cancelled: boolean;
      resolution: ApprovalResolution;
    },
  ): void {
    setMessages((current) => {
      const next = current.map((message) => {
        if (message.id !== messageId) {
          return message;
        }
        return {
          ...message,
          content: result.answer || message.content,
          approvalResolution: result.resolution,
        };
      });
      if (boundIdRef.current) {
        persistBound(boundIdRef.current, next, draftRef.current);
      }
      return next;
    });
  }

  function handleFeedbackChanged(
    messageId: string,
    rating: "positive" | "negative" | null,
  ): void {
    setMessages((current) => {
      const next = current.map((message) => {
        if (message.id !== messageId) {
          return message;
        }
        if ((message.feedbackRating ?? null) === rating) {
          return message;
        }
        return {
          ...message,
          feedbackRating: rating,
        };
      });
      if (boundIdRef.current) {
        persistBound(boundIdRef.current, next, draftRef.current);
      }
      return next;
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

  function runtimeFromSettings(
    style: ConversationResponseStyle,
  ): AskChatOptions["body"]["runtime"] {
    const stored = loadRuntimeSettings();
    const provider: "openrouter" | "ollama" | null =
      stored !== null &&
      (stored.provider === "ollama" || stored.provider === "openrouter")
        ? stored.provider
        : null;
    const base =
      stored === null
        ? null
        : {
            provider,
            model: stored.model,
            settings: stored.settings,
          };
    if (style === "default") {
      return base;
    }
    return {
      ...(base ?? {}),
      response_style: style,
    };
  }

  function handleResponseStyleChange(label: string): void {
    const next = parseStyleLabel(label);
    setResponseStyle(next);
    const id = boundIdRef.current ?? conversationId;
    if (id) {
      updateConversation(id, { responseStyle: next }, { touchUpdatedAt: false });
    }
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
    // Snapshot style for this submit — later SoftSelect changes do not rewrite
    // an in-flight ask body.
    const styleSnapshot = responseStyle;
    const runtime = runtimeFromSettings(styleSnapshot);

    if (isLanding) {
      const withUser = appendUserMessage([], query);
      const conversationIdForRun = newConversationId();
      const created = createConversation({
        id: conversationIdForRun,
        title: titleFromMessages(toPersisted(withUser)),
        messages: toPersisted(withUser),
        draft: "",
        runStatus: "pending",
        requestStartedAt: Date.now(),
        unread: false,
        responseStyle: styleSnapshot,
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
        runtime,
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
      responseStyle: styleSnapshot,
    });
    setSending(true);
    const result = await startConversationRun({
      conversationId: id,
      query,
      history,
      baseUrl: apiBaseUrl,
      ask,
      runtime,
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
        // Drop the empty local shell immediately; clear server memory in
        // the background so a hung backend cannot keep `sending` stuck.
        deleteConversation(id);
        void clearChatCheckpointBestEffort({
          baseUrl: apiBaseUrl,
          conversationId: id,
        });
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

    if (result.kind === "success") {
      const conversation = getConversation(id);
      if (conversation) {
        seedIds(conversation.messages);
        skipNextPersistRef.current = true;
        setMessages(fromPersisted(conversation.messages));
        setDraft(conversation.draft);
      }
      setSending(false);
      setInlineError(null);
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
      const conversation = getConversation(id);
      if (conversation) {
        seedIds(conversation.messages);
        skipNextPersistRef.current = true;
        setMessages(fromPersisted(conversation.messages));
        setDraft(conversation.draft);
      }
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
              testDesignHref={latestTestDesignHref(messages)}
              onTestDesignStarted={handleTestDesignStarted}
              onApprovalResolved={handleApprovalResolved}
              onFeedbackChanged={handleFeedbackChanged}
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
          <div className="kern-chat-composer-toolbar">
            <div className="kern-chat-style">
              {STYLE_ICON}
              <SoftSelect
                id="chat-response-style"
                label="Style"
                value={styleLabel(responseStyle)}
                options={[...RESPONSE_STYLE_OPTIONS]}
                onChange={handleResponseStyleChange}
                menuPlacement="top"
                menuStrategy="fixed"
              />
            </div>
            <button
              type="submit"
              className="kern-chat-send"
              aria-label="Send"
              disabled={sending || !draft.trim() || sendBlocked}
            >
              {SEND_ICON}
            </button>
          </div>
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
