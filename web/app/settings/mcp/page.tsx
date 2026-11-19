import { McpAccessPanel } from "@/components/settings/McpAccessPanel";
import { loadPublicEnv } from "@/lib/env";

export default function McpSettingsPage() {
  const env = loadPublicEnv();
  const mcpPublicEndpoint = `${env.NEXT_PUBLIC_API_BASE_URL}/mcp`;
  return <McpAccessPanel mcpPublicEndpoint={mcpPublicEndpoint} />;
}
