"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { NAV_ITEMS, isActivePath } from "@/lib/navigation";

type SidebarNavProps = {
  open: boolean;
  onNavigate?: () => void;
};

export function SidebarNav({ open, onNavigate }: SidebarNavProps) {
  const pathname = usePathname();

  return (
    <nav
      className={`kern-sidebar${open ? " is-open" : ""}`}
      aria-label="Primary navigation"
    >
      <div className="kern-sidebar-links">
        {NAV_ITEMS.map((item) => {
          const active = isActivePath(pathname, item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`kern-nav-item${active ? " is-active" : ""}`}
              aria-current={active ? "page" : undefined}
              onClick={onNavigate}
            >
              <span>{item.label}</span>
            </Link>
          );
        })}
      </div>
      <div className="kern-foundation-note">
        <span>
          Foundation shell
          <br />
          <small>No API connected</small>
        </span>
      </div>
    </nav>
  );
}
