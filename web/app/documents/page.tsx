import { loadPublicEnv } from "@/lib/env";
import { DocumentsPanel } from "@/components/documents/DocumentsPanel";

export default function DocumentsPage() {
  const env = loadPublicEnv();
  return <DocumentsPanel apiBaseUrl={env.NEXT_PUBLIC_API_BASE_URL} />;
}
