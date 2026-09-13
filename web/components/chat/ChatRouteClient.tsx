"use client";

import { usePathname, useRouter } from "next/navigation";
import { startTransition, useEffect, useState } from "react";
import { ChatPanel } from "@/components/chat/ChatPanel";
import { PreviousChats } from "@/components/chat/PreviousChats";
import {
  loadActiveSession,
  setActiveConversationId,
} from "@/lib/session/active-session";
import {
  getConversation,
  markConversationRead,
} from "@/lib/session/conversations";
import { interruptStalePendingFromCoordinator } from "@/lib/session/conversation-runs";

function conversationIdFromPath(pathname: string): string | null {
  const match = /^\/chat\/([^/]+)\/?$/.exec(pathname);
  return match?.[1] ?? null;
}

/**
 * Stable chat shell for `/chat` and `/chat/[conversationId]`.
 *
 * Conversation layout matches main (plain flex height, composer pinned).
 * UI mode flips immediately on open/create so the Chats list never paints
 * the new row before the transcript appears; soft CSS fade-in only.
 */
export function ChatRouteClient({ apiBaseUrl }: { apiBaseUrl: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const pathConversationId = conversationIdFromPath(pathname);
  const [boundId, setBoundId] = useState<string | null>(pathConversationId);
  const isLanding = boundId === null;

  // Sync from URL when browser back/forward or external navigation.
  useEffect(() => {
    setBoundId(pathConversationId);
  }, [pathConversationId]);

  useEffect(() => {
    interruptStalePendingFromCoordinator();
    if (!boundId) {
      return;
    }
    if (!getConversation(boundId)) {
      setBoundId(null);
      startTransition(() => {
        router.replace("/chat");
      });
      return;
    }
    setActiveConversationId(boundId);
    markConversationRead(boundId);
  }, [boundId, router]);

  useEffect(() => {
    if (!boundId) {
      return;
    }
    return () => {
      if (loadActiveSession().activeConversationId === boundId) {
        setActiveConversationId(null);
      }
    };
  }, [boundId]);

  function openConversation(id: string) {
    // Flip UI first so Chats never flashes the selected/created row.
    setBoundId(id);
    startTransition(() => {
      router.replace(`/chat/${id}`);
    });
  }

  function closeConversation() {
    setBoundId(null);
    startTransition(() => {
      router.replace("/chat");
    });
  }

  if (isLanding) {
    return (
      <div className="kern-chat-landing" data-chat-mode="landing">
        <ChatPanel
          apiBaseUrl={apiBaseUrl}
          conversationId={null}
          variant="landing"
          onConversationCreated={openConversation}
        />
        <div className="kern-chat-landing-history">
          <PreviousChats onSelectConversation={openConversation} />
        </div>
      </div>
    );
  }

  return (
    <div
      className="kern-chat-conversation kern-chat-conversation--enter"
      data-chat-mode="conversation"
    >
      <ChatPanel
        apiBaseUrl={apiBaseUrl}
        conversationId={boundId}
        variant="conversation"
        onConversationClosed={closeConversation}
      />
    </div>
  );
}
