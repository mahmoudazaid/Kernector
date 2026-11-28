import { NextResponse } from "next/server";

/** Liveness probe for Compose / container orchestrators (#486). */
export function GET(): NextResponse {
  return NextResponse.json({ status: "ok" });
}
