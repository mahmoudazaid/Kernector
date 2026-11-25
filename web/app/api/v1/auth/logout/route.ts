import { NextResponse } from "next/server";
import { proxyAuthApi, redactAuthSecrets } from "@/lib/server/auth-proxy";

export async function POST(request: Request): Promise<Response> {
  try {
    return await proxyAuthApi(request, "/api/v1/auth/logout", {
      method: "POST",
    });
  } catch (error) {
    void redactAuthSecrets(
      error instanceof Error ? error.message : "backend unavailable",
    );
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
