import { NextResponse } from "next/server";
import { proxyAuthApi, redactAuthSecrets } from "@/lib/server/auth-proxy";

export async function POST(request: Request): Promise<Response> {
  try {
    const body = await request.text();
    return await proxyAuthApi(request, "/api/v1/auth/login", {
      method: "POST",
      body,
      headers: {
        "Content-Type":
          request.headers.get("content-type") ?? "application/json",
        Origin: request.headers.get("origin") ?? new URL(request.url).origin,
      },
    });
  } catch (error) {
    const message = redactAuthSecrets(
      error instanceof Error ? error.message : "backend unavailable",
    );
    return NextResponse.json(
      {
        type: "https://kernector.dev/problems/backend_unavailable",
        title: "Backend unavailable",
        status: 502,
        detail: message.includes("password")
          ? "The API could not be reached."
          : "The API could not be reached.",
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
}
