export type NavItem = {
  label: string;
  href: string;
};

export const PRODUCT_LABEL = "Multi-source knowledge hub";

export const NAV_ITEMS: readonly NavItem[] = [
  { label: "Dashboard", href: "/" },
  { label: "Documents", href: "/documents" },
  { label: "Chat", href: "/chat" },
  { label: "Settings", href: "/settings" },
] as const;

export function isActivePath(pathname: string, href: string): boolean {
  if (href === "/") {
    return pathname === "/";
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function navItemForPath(pathname: string): NavItem {
  return (
    NAV_ITEMS.find((item) => isActivePath(pathname, item.href)) ?? NAV_ITEMS[0]
  );
}
