import { loadPublicEnv } from "@/lib/env";
import { ChatPanel } from "@/components/chat/ChatPanel";

export default function ChatPage() {
  const env = loadPublicEnv();
  return <ChatPanel apiBaseUrl={env.NEXT_PUBLIC_API_BASE_URL} />;
}
