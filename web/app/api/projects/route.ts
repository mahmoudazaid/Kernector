import { NextResponse } from "next/server";
import { proxyApi } from "@/lib/server/api-proxy";

export async function GET(): Promise<Response> {
  try {
    const upstream = await proxyApi("/api/v1/projects");
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
