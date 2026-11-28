import { NextResponse } from "next/server";
import { proxyAuthApi, redactAuthSecrets } from "@/lib/server/auth-proxy";

export async function GET(request: Request): Promise<Response> {
  try {
    return await proxyAuthApi(request, "/api/v1/projects", { method: "GET" });
  } catch (error) {
    console.error(
      "projects BFF proxy failed:",
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
