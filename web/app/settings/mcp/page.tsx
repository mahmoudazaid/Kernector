import { McpAccessPanel } from "@/components/settings/McpAccessPanel";
import { loadPublicEnv } from "@/lib/env";

const DEFAULT_MCP_ENDPOINT = "http://127.0.0.1:8100/mcp";

export default function McpSettingsPage() {
  const env = loadPublicEnv();
  const raw = process.env.NEXT_PUBLIC_MCP_URL?.trim();
  const mcpPublicEndpoint = raw
    ? raw.replace(/\/+$/, "")
    : DEFAULT_MCP_ENDPOINT;
  return (
    <McpAccessPanel
      mcpPublicEndpoint={mcpPublicEndpoint}
      apiBaseUrl={env.NEXT_PUBLIC_API_BASE_URL}
    />
  );
}
