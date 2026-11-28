import type { ReactNode } from "react";
import { ChatShell } from "@/components/chat/ChatShell";

/**
 * Persistent chat shell — ChatPanel stays mounted across `/chat` ↔ `/chat/[id]`.
 * Page slots render null; routing is driven by pathname inside ChatRouteClient.
 * Same-origin BFF so kernector_session reaches FastAPI (#447).
 */
const BFF = "";

export default function ChatLayout({ children }: { children: ReactNode }) {
  return (
    <div className="kern-chat-shell">
      <ChatShell apiBaseUrl={BFF} />
      {/* Keep the App Router page slot mounted (may suspend); UI lives in ChatShell. */}
      <div className="kern-chat-route-slot" aria-hidden="true">
        {children}
      </div>
    </div>
  );
}
