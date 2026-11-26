"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";
import { NAV_ITEMS, isActivePath } from "@/lib/navigation";
import { useAuthOptional } from "@/lib/auth/use-auth";

type SidebarNavProps = {
  open: boolean;
  onNavigate?: () => void;
};

export function SidebarNav({ open, onNavigate }: SidebarNavProps) {
  const pathname = usePathname();
  const router = useRouter();
  const auth = useAuthOptional();
  const [signOutError, setSignOutError] = useState<string | null>(null);
  const [signingOut, setSigningOut] = useState(false);

  async function handleSignOut(): Promise<void> {
    if (!auth) {
      return;
    }
    setSignOutError(null);
    setSigningOut(true);
    try {
      await auth.signOut();
      onNavigate?.();
      router.replace("/login");
    } catch {
      setSignOutError("Sign out failed. Please try again.");
    } finally {
      setSigningOut(false);
    }
  }

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
        {auth?.user ? (
          <>
            <button
              type="button"
              className="kern-nav-item"
              disabled={signingOut}
              onClick={() => void handleSignOut()}
            >
              {signingOut ? "Signing out…" : "Sign out"}
            </button>
            {signOutError ? (
              <p className="kern-nav-error" role="alert">
                {signOutError}
              </p>
            ) : null}
          </>
        ) : null}
      </div>
      {auth?.user ? (
        <div className="kern-nav-auth">
          <span
            className="kern-nav-item kern-nav-user"
            title={auth.user.username}
          >
            {auth.user.username}
          </span>
        </div>
      ) : null}
    </nav>
  );
}
