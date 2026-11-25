"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";
import { PRODUCT_LABEL } from "@/lib/navigation";
import { KernectorMark } from "@/components/shell/KernectorMark";
import { SidebarNav } from "@/components/shell/SidebarNav";
import { ThemeToggle } from "@/components/shell/ThemeToggle";
import { useAuthOptional } from "@/lib/auth/use-auth";

type AppShellProps = {
  children: ReactNode;
};

export function AppShell({ children }: AppShellProps) {
  const [navOpen, setNavOpen] = useState(false);
  const pathname = usePathname();
  const auth = useAuthOptional();
  const isLogin = pathname === "/login";
  // Outside AuthProvider (tests): keep workspace nav. In-app: require session.
  const showWorkspaceNav =
    !isLogin && (auth === null || auth.user !== null);

  return (
    <div className={`kern-app${isLogin ? " is-login" : ""}`}>
      <header className="kern-header">
        {showWorkspaceNav ? (
          <button
            className="kern-menu"
            type="button"
            aria-label={navOpen ? "Close navigation" : "Open navigation"}
            aria-expanded={navOpen}
            onClick={() => setNavOpen((open) => !open)}
          >
            <svg
              className="kern-menu-icon"
              viewBox="0 0 20 20"
              fill="none"
              aria-hidden="true"
            >
              {navOpen ? (
                <path
                  d="M5 5l10 10M15 5L5 15"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                />
              ) : (
                <path
                  d="M4 6.5h12M4 10h12M4 13.5h12"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                />
              )}
            </svg>
          </button>
        ) : null}
        <Link
          className="kern-brand"
          href={showWorkspaceNav ? "/" : "/login"}
          aria-label="Kernector home"
        >
          <KernectorMark className="kern-brand-mark" />
          <span className="kern-brand-text">ERNECTOR</span>
        </Link>
        <span className="kern-product-label">{PRODUCT_LABEL}</span>
        <ThemeToggle />
      </header>
      <div className="kern-body">
        {showWorkspaceNav ? (
          <SidebarNav open={navOpen} onNavigate={() => setNavOpen(false)} />
        ) : null}
        <main className="kern-main">{children}</main>
      </div>
    </div>
  );
}
