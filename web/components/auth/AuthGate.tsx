"use client";

import { useEffect, type ReactNode } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { LoadingState } from "@/components/states/LoadingState";
import { useAuth } from "@/lib/auth/use-auth";

const LOGIN_PATH = "/login";

function safeNextPath(raw: string | null): string {
  if (!raw || !raw.startsWith("/") || raw.startsWith("//")) {
    return "/";
  }
  if (raw === LOGIN_PATH || raw.startsWith(`${LOGIN_PATH}?`)) {
    return "/";
  }
  return raw;
}

/**
 * Require a signed-in session for every product route.
 * `/login` is the only ungated page surface.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const auth = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const isLogin = pathname === LOGIN_PATH;
  const resolving = auth.preferencesStatus === "loading";

  useEffect(() => {
    if (resolving) {
      return;
    }
    if (!auth.user && !isLogin) {
      const next = `${pathname}${searchParams.toString() ? `?${searchParams}` : ""}`;
      const target = `${LOGIN_PATH}?next=${encodeURIComponent(next)}`;
      router.replace(target);
      return;
    }
    if (auth.user && isLogin) {
      router.replace(safeNextPath(searchParams.get("next")));
    }
  }, [
    auth.user,
    isLogin,
    pathname,
    resolving,
    router,
    searchParams,
  ]);

  if (resolving) {
    return (
      <div className="kern-content-state" aria-busy="true">
        <LoadingState label="Checking session" />
      </div>
    );
  }

  if (!auth.user && !isLogin) {
    return (
      <div className="kern-content-state" aria-busy="true">
        <LoadingState label="Redirecting to login" />
      </div>
    );
  }

  if (auth.user && isLogin) {
    return (
      <div className="kern-content-state" aria-busy="true">
        <LoadingState label="Opening workspace" />
      </div>
    );
  }

  return children;
}
