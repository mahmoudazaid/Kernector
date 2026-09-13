"use client";

import { useEffect } from "react";
import { ChatPanel } from "@/components/chat/ChatPanel";
import {
  loadActiveSession,
  setActiveConversationId,
} from "@/lib/session/active-session";
import { markConversationRead } from "@/lib/session/conversations";
import { interruptStalePendingFromCoordinator } from "@/lib/session/conversation-runs";

/**
 * `/chat/{conversationId}` — selected transcript + composer only.
 */
export function ConversationView({
  apiBaseUrl,
  conversationId,
}: {
  apiBaseUrl: string;
  conversationId: string;
}) {
  useEffect(() => {
    interruptStalePendingFromCoordinator();
    setActiveConversationId(conversationId);
    markConversationRead(conversationId);
  }, [conversationId]);

  useEffect(() => {
    return () => {
      if (loadActiveSession().activeConversationId === conversationId) {
        setActiveConversationId(null);
      }
    };
  }, [conversationId]);

  return (
    <div className="kern-chat-conversation">
      <ChatPanel
        apiBaseUrl={apiBaseUrl}
        conversationId={conversationId}
        variant="conversation"
      />
    </div>
  );
}
