import { NextResponse } from "next/server";
import { adminMcpBffError } from "@/lib/server/admin-mcp-bff";
import { proxyAdminMcp } from "@/lib/server/admin-mcp-proxy";

type Params = { params: Promise<{ profileId: string }> };

export async function PUT(
  request: Request,
  { params }: Params,
): Promise<Response> {
  const { profileId } = await params;
  try {
    const payload = await request.text();
    const upstream = await proxyAdminMcp(
      `/api/v1/admin/mcp/profiles/${encodeURIComponent(profileId)}/allowlist`,
      { method: "PUT", body: payload },
    );
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
