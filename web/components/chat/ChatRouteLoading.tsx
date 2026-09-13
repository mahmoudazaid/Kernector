"use client";

import { KernectorThinkingMark } from "@/components/shell/KernectorThinkingMark";
import { loadActiveSession } from "@/lib/session/active-session";
import { getConversation } from "@/lib/session/conversations";

/**
 * Instant chat chrome while `/chat` ↔ `/chat/[id]` navigates.
 * Avoids the root brand loader; seeds from the active conversation when present.
 */
export function ChatRouteLoading() {
  const activeId = loadActiveSession().activeConversationId;
  const conversation = activeId ? getConversation(activeId) : null;
  const pending = conversation?.runStatus === "pending";
  const messages = conversation?.messages ?? [];

  return (
    <div className="kern-chat-conversation" aria-busy="true">
      <section className="kern-chat">
        <header className="kern-chat-header">
          <h1>Chat</h1>
        </header>
        <div className="kern-chat-body">
          <div className="kern-chat-thread" aria-live="polite">
            {messages.map((message) =>
              message.role === "user" ? (
                <article
                  key={message.id}
                  className="kern-chat-msg kern-chat-msg--user"
                  data-role="user"
                >
                  <p>{message.content}</p>
                </article>
              ) : (
                <article
                  key={message.id}
                  className="kern-chat-msg kern-chat-msg--assistant"
                  data-role="assistant"
                >
                  <div className="kern-chat-answer">{message.content}</div>
                </article>
              ),
            )}
            {pending || messages.length === 0 ? (
              <p className="kern-chat-thinking" role="status">
                <KernectorThinkingMark className="kern-chat-thinking-mark" />
                <span className="visually-hidden">
                  {pending ? "Thinking…" : "Loading conversation…"}
                </span>
              </p>
            ) : null}
          </div>
        </div>
      </section>
    </div>
  );
}
