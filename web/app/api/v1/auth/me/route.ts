import { NextResponse } from "next/server";
import { proxyAuthApi, redactAuthSecrets } from "@/lib/server/auth-proxy";

export async function GET(request: Request): Promise<Response> {
  try {
    return await proxyAuthApi(request, "/api/v1/auth/me", { method: "GET" });
  } catch (error) {
    const raw = error instanceof Error ? error.message : "backend unavailable";
    console.error("[auth/me]", redactAuthSecrets(raw));
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
}
