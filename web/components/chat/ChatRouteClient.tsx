"use client";

import { usePathname, useRouter } from "next/navigation";
import { startTransition, useEffect, useState } from "react";
import { ChatPanel, type ChatPanelProps } from "@/components/chat/ChatPanel";
import { PreviousChats } from "@/components/chat/PreviousChats";
import {
  loadActiveSession,
  setActiveConversationId,
} from "@/lib/session/active-session";
import {
  getConversation,
  markConversationRead,
} from "@/lib/session/conversations";
import { scheduleStalePendingSweep } from "@/lib/session/conversation-runs";

function conversationIdFromPath(pathname: string): string | null {
  const match = /^\/chat\/([^/]+)\/?$/.exec(pathname);
  return match?.[1] ?? null;
}

/**
 * Stable chat shell for `/chat` and `/chat/[conversationId]`.
 *
 * One ChatPanel instance stays mounted across landing ↔ conversation so
 * in-flight asks cannot corrupt another thread's UI, and close handoffs can
 * preserve draft/error on `/chat`.
 */
export function ChatRouteClient({
  apiBaseUrl,
  ask,
  loadSettings,
}: {
  apiBaseUrl: string;
  ask?: ChatPanelProps["ask"];
  loadSettings?: ChatPanelProps["loadSettings"];
}) {
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
    const cancelSweep = scheduleStalePendingSweep();
    if (!boundId) {
      return cancelSweep;
    }
    if (!getConversation(boundId)) {
      setBoundId(null);
      startTransition(() => {
        router.replace("/chat");
      });
      return cancelSweep;
    }
    setActiveConversationId(boundId);
    markConversationRead(boundId);
    return cancelSweep;
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

  return (
    <div
      className={
        isLanding
          ? "kern-chat-landing"
          : "kern-chat-conversation kern-chat-conversation--enter"
      }
      data-chat-mode={isLanding ? "landing" : "conversation"}
    >
      <ChatPanel
        apiBaseUrl={apiBaseUrl}
        conversationId={boundId}
        variant={isLanding ? "landing" : "conversation"}
        ask={ask}
        loadSettings={loadSettings}
        onConversationCreated={openConversation}
        onConversationClosed={closeConversation}
      />
      {isLanding ? (
        <div className="kern-chat-landing-history">
          <PreviousChats
            apiBaseUrl={apiBaseUrl}
            onSelectConversation={openConversation}
          />
        </div>
      ) : null}
    </div>
  );
}
