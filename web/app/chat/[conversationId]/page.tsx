type ChatConversationPageProps = {
  params: Promise<{ conversationId: string }>;
};

/** Route identity for `/chat/[id]` — UI is owned by the persistent chat layout shell. */
export default async function ChatConversationPage({
  params,
}: ChatConversationPageProps) {
  await params;
  return null;
}
