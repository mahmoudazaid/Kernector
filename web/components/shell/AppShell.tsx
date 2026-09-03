"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";
import { PRODUCT_LABEL } from "@/lib/navigation";
import { SidebarNav } from "@/components/shell/SidebarNav";
import { ThemeToggle } from "@/components/shell/ThemeToggle";

type AppShellProps = {
  children: ReactNode;
};

export function AppShell({ children }: AppShellProps) {
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
          <span aria-hidden="true">{navOpen ? "✕" : "☰"}</span>
        </button>
        <Link className="kern-brand" href="/" aria-label="Kernector home">
          <span className="kern-brand-mark" aria-hidden="true">
            K
          </span>
          <span className="kern-brand-text">Kernector</span>
        </Link>
        <span className="kern-product-label">{PRODUCT_LABEL}</span>
        <ThemeToggle />
      </header>
      <div className="kern-body">
        <SidebarNav open={navOpen} onNavigate={() => setNavOpen(false)} />
        <main className="kern-main">{children}</main>
      </div>
    </div>
  );
}
