import { NextResponse } from "next/server";
import { adminMcpBffError } from "@/lib/server/admin-mcp-bff";
import { proxyAdminMcp } from "@/lib/server/admin-mcp-proxy";

export async function GET(): Promise<Response> {
  try {
    const upstream = await proxyAdminMcp("/api/v1/admin/mcp/server");
    const body = await upstream.text();
    return new NextResponse(body, {
      status: upstream.status,
      headers: {
        "Content-Type":
          upstream.headers.get("Content-Type") ?? "application/json",
      },
    });
  } catch (error) {
    return adminMcpBffError(error);
  }
}
