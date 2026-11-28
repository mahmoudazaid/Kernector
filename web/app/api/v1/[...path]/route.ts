import { NextResponse } from "next/server";
import { proxyAuthApi, redactAuthSecrets } from "@/lib/server/auth-proxy";

/**
 * Cookie-forwarding BFF for product FastAPI routes (#447).
 * More-specific handlers (auth, preferences, admin MCP, projects) take
 * precedence; this catch-all covers documents, chat, connectors, etc.
 */
async function proxyProductApi(
  request: Request,
  context: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  const { path } = await context.params;
  const url = new URL(request.url);
  const upstreamPath = `/api/v1/${path.join("/")}${url.search}`;

  try {
    const init: RequestInit = { method: request.method };
    if (request.method !== "GET" && request.method !== "HEAD") {
      init.body = await request.arrayBuffer();
      const contentType = request.headers.get("content-type");
      if (contentType) {
        init.headers = { "Content-Type": contentType };
      }
    }
    return await proxyAuthApi(request, upstreamPath, init);
  } catch (error) {
    console.error(
      "product BFF proxy failed:",
      redactAuthSecrets(String(error)),
    );
    return NextResponse.json(
      {
        type: "https://kernector.dev/problems/backend_unavailable",
        title: "Backend unavailable",
        status: 502,
        detail: "The API could not be reached.",
        code: "backend_unavailable",
      },
      { status: 502, headers: { "Content-Type": "application/problem+json" } },
    );
  }
}

export const GET = proxyProductApi;
export const POST = proxyProductApi;
export const PUT = proxyProductApi;
export const PATCH = proxyProductApi;
export const DELETE = proxyProductApi;
