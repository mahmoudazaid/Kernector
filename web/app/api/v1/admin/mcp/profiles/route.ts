import { NextResponse } from "next/server";
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
  } catch {
    return NextResponse.json(
      {
        type: "https://kernector.dev/problems/unauthorized",
        title: "Unauthorized",
        status: 401,
        detail: "Authentication is required.",
        code: "unauthorized",
      },
      { status: 401, headers: { "Content-Type": "application/problem+json" } },
    );
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
  } catch {
    return NextResponse.json(
      {
        type: "https://kernector.dev/problems/unauthorized",
        title: "Unauthorized",
        status: 401,
        detail: "Authentication is required.",
        code: "unauthorized",
      },
      { status: 401, headers: { "Content-Type": "application/problem+json" } },
    );
  }
}
