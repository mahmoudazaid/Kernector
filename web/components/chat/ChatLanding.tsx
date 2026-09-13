"use client";

import { useRouter } from "next/navigation";
import { useEffect, startTransition } from "react";
import { ChatPanel } from "@/components/chat/ChatPanel";
import { PreviousChats } from "@/components/chat/PreviousChats";
import { interruptStalePendingFromCoordinator } from "@/lib/session/conversation-runs";

/**
 * `/chat` landing — empty composer + Chats list only.
 * Never hydrates or displays a conversation transcript.
 */
export function ChatLanding({ apiBaseUrl }: { apiBaseUrl: string }) {
  const router = useRouter();

  useEffect(() => {
    interruptStalePendingFromCoordinator();
  }, []);

  return (
    <div className="kern-chat-landing">
      <ChatPanel
        apiBaseUrl={apiBaseUrl}
        conversationId={null}
        variant="landing"
        onConversationCreated={(id) => {
          startTransition(() => {
            router.replace(`/chat/${id}`);
          });
        }}
      />
      <PreviousChats />
    </div>
  );
}
