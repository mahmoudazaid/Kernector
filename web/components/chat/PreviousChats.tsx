"use client";

import Link from "next/link";
import {
  useEffect,
  useId,
  useRef,
  useState,
  useSyncExternalStore,
  type KeyboardEvent,
} from "react";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { KernectorThinkingMark } from "@/components/shell/KernectorThinkingMark";
import { EmptyState } from "@/components/states/EmptyState";
import { formatTimestamp } from "@/lib/format/timestamp";
import {
  loadActiveSession,
  setActiveConversationId,
} from "@/lib/session/active-session";
import {
  deleteConversation,
  getConversationsSnapshot,
  getServerConversationsSnapshot,
  renameConversation,
  subscribeConversations,
  type Conversation,
} from "@/lib/session/conversations";
import { clearChatCheckpointBestEffort } from "@/lib/api/chat";

function OverflowMenu({
  conversation,
  onRename,
  onDelete,
}: {
  conversation: Conversation;
  onRename: () => void;
  onDelete: () => void;
}) {
  const [open, setOpen] = useState(false);
  const menuId = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    function onPointerDown(event: PointerEvent) {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  function onTriggerKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (
      event.key === "ArrowDown" ||
      event.key === "Enter" ||
      event.key === " "
    ) {
      event.preventDefault();
      setOpen(true);
    }
  }

  function onMenuKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      setOpen(false);
      triggerRef.current?.focus();
    }
  }

  const actionsLabel = `Conversation actions for ${conversation.title}`;

  return (
    <div className="kern-chat-overflow" ref={rootRef}>
      <button
        ref={triggerRef}
        type="button"
        className="kern-chat-overflow-trigger"
        aria-label={actionsLabel}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          setOpen((current) => !current);
        }}
        onKeyDown={onTriggerKeyDown}
      >
        <svg
          className="kern-chat-overflow-icon"
          viewBox="0 0 24 24"
          fill="none"
          aria-hidden="true"
        >
          <path
            d="M12 5v.01M12 12v.01M12 19v.01M12 6a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2z"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>
      {open ? (
        <div
          id={menuId}
          className="kern-chat-overflow-menu"
          role="menu"
          aria-label={actionsLabel}
          onKeyDown={onMenuKeyDown}
        >
          <button
            type="button"
            role="menuitem"
            className="kern-chat-overflow-item"
            onClick={(event) => {
              event.preventDefault();
              event.stopPropagation();
              setOpen(false);
              onRename();
            }}
          >
            Rename
          </button>
          <button
            type="button"
            role="menuitem"
            className="kern-chat-overflow-item kern-chat-overflow-item--danger"
            onClick={(event) => {
              event.preventDefault();
              event.stopPropagation();
              setOpen(false);
              onDelete();
            }}
          >
            Delete
          </button>
        </div>
      ) : null}
    </div>
  );
}

function RowStatusBesideTitle({
  conversation,
}: {
  conversation: Conversation;
}) {
  if (conversation.runStatus === "pending") {
    return (
      <span
        className="kern-previous-chats-status kern-previous-chats-status--pending"
        role="status"
        aria-label="Request in progress"
      >
        <KernectorThinkingMark className="kern-previous-chats-thinking-mark" />
      </span>
    );
  }
  if (conversation.runStatus === "failed") {
    return (
      <span
        className="kern-previous-chats-status kern-previous-chats-status--failed"
        role="status"
        aria-label="Request failed"
      />
    );
  }
  return null;
}

/**
 * Landing-only conversation list (below the empty `/chat` composer).
 * Code name: PreviousChats.
 */
export function PreviousChats({
  onSelectConversation,
  apiBaseUrl,
}: {
  /** When set, opens via callback instead of a hard Link navigation. */
  onSelectConversation?: (conversationId: string) => void;
  /** API base for clearing short-term agent checkpoints on delete. */
  apiBaseUrl?: string;
} = {}) {
  const conversations = useSyncExternalStore(
    subscribeConversations,
    getConversationsSnapshot,
    getServerConversationsSnapshot,
  );
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [pendingDelete, setPendingDelete] = useState<Conversation | null>(null);

  function startRename(conversation: Conversation): void {
    setRenamingId(conversation.id);
    setRenameValue(conversation.title);
  }

  function commitRename(): void {
    if (!renamingId) {
      return;
    }
    renameConversation(renamingId, renameValue);
    setRenamingId(null);
    setRenameValue("");
  }

  function confirmDelete(): void {
    if (!pendingDelete) {
      return;
    }
    const id = pendingDelete.id;
    deleteConversation(id);
    setPendingDelete(null);
    if (loadActiveSession().activeConversationId === id) {
      setActiveConversationId(null);
    }
    if (apiBaseUrl) {
      void clearChatCheckpointBestEffort({
        baseUrl: apiBaseUrl,
        conversationId: id,
      });
    }
  }

  return (
    <section
      className="kern-previous-chats"
      {...(conversations.length === 0
        ? { "aria-label": "Chats" }
        : { "aria-labelledby": "previous-chats-heading" })}
    >
      {conversations.length === 0 ? (
        <div className="kern-previous-chats-empty">
          <EmptyState
            title="No chats yet"
            description="Ask a question above to start your first conversation."
          />
        </div>
      ) : (
        <>
          <h2 id="previous-chats-heading" className="kern-previous-chats-title">
            Chats
          </h2>
          <ul className="kern-previous-chats-list">
            {conversations.map((conversation) => {
              const iso = new Date(conversation.updatedAt).toISOString();
              return (
                <li key={conversation.id} className="kern-previous-chats-card">
                  {renamingId === conversation.id ? (
                    <form
                      className="kern-previous-chats-rename"
                      onSubmit={(event) => {
                        event.preventDefault();
                        commitRename();
                      }}
                    >
                      <label
                        className="visually-hidden"
                        htmlFor={`rename-${conversation.id}`}
                      >
                        Rename conversation
                      </label>
                      <input
                        id={`rename-${conversation.id}`}
                        value={renameValue}
                        autoFocus
                        onChange={(event) =>
                          setRenameValue(event.target.value)
                        }
                        onBlur={commitRename}
                      />
                    </form>
                  ) : (
                    <>
                      <Link
                        href={`/chat/${conversation.id}`}
                        className="kern-previous-chats-row"
                        onClick={(event) => {
                          if (!onSelectConversation) {
                            return;
                          }
                          event.preventDefault();
                          onSelectConversation(conversation.id);
                        }}
                      >
                        <span className="kern-previous-chats-row-main">
                          {conversation.unread &&
                          conversation.runStatus !== "pending" &&
                          conversation.runStatus !== "failed" ? (
                            <span
                              className="kern-previous-chats-status kern-previous-chats-status--unread"
                              aria-label="Unread response"
                            />
                          ) : null}
                          <span className="kern-previous-chats-row-title">
                            {conversation.title}
                          </span>
                          <RowStatusBesideTitle conversation={conversation} />
                        </span>
                        <span className="kern-previous-chats-row-meta">
                          <time
                            className="kern-previous-chats-row-time"
                            dateTime={iso}
                          >
                            {formatTimestamp(iso)}
                          </time>
                        </span>
                      </Link>
                      <OverflowMenu
                        conversation={conversation}
                        onRename={() => startRename(conversation)}
                        onDelete={() => setPendingDelete(conversation)}
                      />
                    </>
                  )}
                </li>
              );
            })}
          </ul>
        </>
      )}
      <ConfirmDialog
        open={pendingDelete !== null}
        title="Delete conversation"
        description={
          pendingDelete
            ? `Delete “${pendingDelete.title}”? This cannot be undone.`
            : ""
        }
        confirmLabel="Delete"
        tone="danger"
        onCancel={() => setPendingDelete(null)}
        onConfirm={confirmDelete}
      />
    </section>
  );
}
