import type { ReactNode } from "react";
import { ChatShell } from "@/components/chat/ChatShell";
import { loadPublicEnv } from "@/lib/env";

/**
 * Persistent chat shell — ChatPanel stays mounted across `/chat` ↔ `/chat/[id]`.
 * Page slots render null; routing is driven by pathname inside ChatRouteClient.
 */
export default function ChatLayout({ children }: { children: ReactNode }) {
  const env = loadPublicEnv();
  return (
    <div className="kern-chat-shell">
      <ChatShell apiBaseUrl={env.NEXT_PUBLIC_API_BASE_URL} />
      {/* Keep the App Router page slot mounted (may suspend); UI lives in ChatShell. */}
      <div className="kern-chat-route-slot" aria-hidden="true">
        {children}
      </div>
    </div>
  );
}
