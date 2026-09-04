"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";
import { PRODUCT_LABEL } from "@/lib/navigation";
import { BackendStatus } from "@/components/shell/BackendStatus";
import { SidebarNav } from "@/components/shell/SidebarNav";
import { ThemeToggle } from "@/components/shell/ThemeToggle";

type AppShellProps = {
  children: ReactNode;
  apiBaseUrl: string;
};

export function AppShell({ children, apiBaseUrl }: AppShellProps) {
  const [navOpen, setNavOpen] = useState(false);

  return (
    <div className="kern-app">
      <header className="kern-header">
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
        <Link className="kern-brand" href="/" aria-label="Kernector home">
          <span className="kern-brand-mark" aria-hidden="true">
            K
          </span>
          <span className="kern-brand-text">Kernector</span>
        </Link>
        <span className="kern-product-label">{PRODUCT_LABEL}</span>
        <BackendStatus apiBaseUrl={apiBaseUrl} />
        <ThemeToggle />
      </header>
      <div className="kern-body">
        <SidebarNav open={navOpen} onNavigate={() => setNavOpen(false)} />
        <main className="kern-main">{children}</main>
      </div>
    </div>
  );
}
