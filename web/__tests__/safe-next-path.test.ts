import { describe, expect, it } from "vitest";
import { safeNextPath } from "@/lib/auth/safe-next-path";

const ORIGIN = "http://localhost:3000";

describe("safeNextPath", () => {
  it("allows same-origin relative paths", () => {
    expect(safeNextPath("/chat", ORIGIN)).toBe("/chat");
    expect(safeNextPath("/settings?tab=1", ORIGIN)).toBe("/settings?tab=1");
  });

  it("rejects protocol-relative and absolute external URLs", () => {
    expect(safeNextPath("//evil.test/p", ORIGIN)).toBe("/");
    expect(safeNextPath("https://evil.test/", ORIGIN)).toBe("/");
  });

  it("rejects backslash and tab smuggling", () => {
    expect(safeNextPath("/%5Cevil.test/p", ORIGIN)).toBe("/");
    expect(safeNextPath("/%09/evil.test/p", ORIGIN)).toBe("/");
    expect(safeNextPath("/\\evil.test/p", ORIGIN)).toBe("/");
  });

  it("rejects login loops and empty/null", () => {
    expect(safeNextPath("/login", ORIGIN)).toBe("/");
    expect(safeNextPath("/login?next=%2F", ORIGIN)).toBe("/");
    expect(safeNextPath(null, ORIGIN)).toBe("/");
    expect(safeNextPath(undefined, ORIGIN)).toBe("/");
  });
});
