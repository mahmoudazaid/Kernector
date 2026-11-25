/**
 * Resolve a post-login `next` path that stays same-origin.
 * Rejects protocol-relative URLs and backslash/tab smuggling used in open redirects.
 */
export function safeNextPath(
  raw: string | null | undefined,
  origin: string,
): string {
  if (!raw) {
    return "/";
  }
  let resolved: URL;
  try {
    resolved = new URL(raw, origin);
  } catch {
    return "/";
  }
  const base = new URL(origin);
  if (resolved.origin !== base.origin) {
    return "/";
  }

  let decodedPath: string;
  try {
    decodedPath = decodeURIComponent(resolved.pathname);
  } catch {
    return "/";
  }
  // Control chars / backslash can be re-parsed by browsers as a new authority.
  if (/[\u0000-\u001f\\]/.test(decodedPath) || decodedPath.startsWith("//")) {
    return "/";
  }
  if (
    resolved.pathname === "/login" ||
    resolved.pathname.startsWith("/login/")
  ) {
    return "/";
  }
  if (!resolved.pathname.startsWith("/")) {
    return "/";
  }
  return `${resolved.pathname}${resolved.search}${resolved.hash}`;
}
