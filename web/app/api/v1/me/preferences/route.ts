import { NextResponse } from "next/server";
import { proxyAuthApi, redactAuthSecrets } from "@/lib/server/auth-proxy";

export async function GET(request: Request): Promise<Response> {
  try {
    return await proxyAuthApi(request, "/api/v1/me/preferences", {
      method: "GET",
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

export async function PUT(request: Request): Promise<Response> {
  try {
    const body = await request.text();
    return await proxyAuthApi(request, "/api/v1/me/preferences", {
      method: "PUT",
      body,
      headers: {
        "Content-Type":
          request.headers.get("content-type") ?? "application/json",
      },
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
