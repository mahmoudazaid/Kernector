import { NextResponse } from "next/server";
import { adminMcpBffError } from "@/lib/server/admin-mcp-bff";
import { proxyAdminMcp } from "@/lib/server/admin-mcp-proxy";

export async function GET(): Promise<Response> {
  try {
    const upstream = await proxyAdminMcp("/api/v1/admin/mcp/profiles");
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

export async function POST(request: Request): Promise<Response> {
  try {
    const payload = await request.text();
    const upstream = await proxyAdminMcp("/api/v1/admin/mcp/profiles", {
      method: "POST",
      body: payload,
    });
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
