export type NavItem = {
  label: string;
  href: string;
};

export const PRODUCT_LABEL = "Multi-source knowledge hub";

export const NAV_ITEMS: readonly NavItem[] = [
  { label: "Dashboard", href: "/" },
  { label: "Knowledge Hub", href: "/documents" },
  { label: "Chat", href: "/chat" },
  { label: "Settings", href: "/settings" },
  { label: "MCP Access", href: "/settings/mcp" },
] as const;

function pathMatchesHref(pathname: string, href: string): boolean {
  if (href === "/") {
    return pathname === "/";
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}

/**
 * True when ``href`` is the most specific nav match for ``pathname``.
 * Avoids parent routes (e.g. ``/settings``) staying active on children
 * (e.g. ``/settings/mcp``).
 */
export function isActivePath(pathname: string, href: string): boolean {
  if (!pathMatchesHref(pathname, href)) {
    return false;
  }
  const moreSpecific = NAV_ITEMS.some(
    (item) =>
      item.href !== href &&
      item.href.length > href.length &&
      pathMatchesHref(pathname, item.href),
  );
  return !moreSpecific;
}

export function navItemForPath(pathname: string): NavItem {
  let best: NavItem | undefined;
  for (const item of NAV_ITEMS) {
    if (!pathMatchesHref(pathname, item.href)) {
      continue;
    }
    if (!best || item.href.length > best.href.length) {
      best = item;
    }
  }
  return best ?? NAV_ITEMS[0];
}
