import { NextResponse } from "next/server";
import { proxyAuthApi, redactAuthSecrets } from "@/lib/server/auth-proxy";

function backendUnavailable(error: unknown): Response {
  const raw = error instanceof Error ? error.message : "backend unavailable";
  console.error("[auth/login]", redactAuthSecrets(raw));
  return NextResponse.json(
    {
      type: "https://kernector.dev/problems/backend_unavailable",
      title: "Backend unavailable",
      status: 502,
      detail: "The API could not be reached.",
      code: "backend_unavailable",
    },
    {
      status: 502,
      headers: {
        "Content-Type": "application/problem+json",
        "Cache-Control": "no-store",
      },
    },
  );
}

export async function POST(request: Request): Promise<Response> {
  try {
    const body = await request.text();
    const headers: Record<string, string> = {
      "Content-Type":
        request.headers.get("content-type") ?? "application/json",
    };
    // Forward Origin only when the browser sent one — never invent a trusted
    // origin (ADR 0013 §5).
    const origin = request.headers.get("origin");
    if (origin) {
      headers.Origin = origin;
    }
    return await proxyAuthApi(request, "/api/v1/auth/login", {
      method: "POST",
      body,
      headers,
    });
  } catch (error) {
    return backendUnavailable(error);
  }
}
