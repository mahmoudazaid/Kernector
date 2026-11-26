"use client";

import { useEffect, type ReactNode } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import { safeNextPath } from "@/lib/auth/safe-next-path";
import { useAuth } from "@/lib/auth/use-auth";

const LOGIN_PATH = "/login";

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
  const unavailable = auth.preferencesStatus === "unavailable";

  useEffect(() => {
    if (resolving || unavailable) {
      return;
    }
    if (!auth.user && !isLogin) {
      const next = `${pathname}${searchParams.toString() ? `?${searchParams}` : ""}`;
      const target = `${LOGIN_PATH}?next=${encodeURIComponent(next)}`;
      router.replace(target);
      return;
    }
    if (auth.user && isLogin) {
      router.replace(
        safeNextPath(searchParams.get("next"), window.location.origin),
      );
    }
  }, [
    auth.user,
    isLogin,
    pathname,
    resolving,
    unavailable,
    router,
    searchParams,
  ]);

  if (resolving) {
    return (
      <div aria-busy="true">
        <div className="kern-content-state">
          <LoadingState label="Checking session" />
        </div>
      </div>
    );
  }

  if (unavailable) {
    return (
      <div className="kern-content-state">
        <ErrorState onRetry={() => void auth.refresh()} />
      </div>
    );
  }

  if (!auth.user && !isLogin) {
    return (
      <div aria-busy="true">
        <div className="kern-content-state">
          <LoadingState label="Redirecting to login" />
        </div>
      </div>
    );
  }

  if (auth.user && isLogin) {
    return (
      <div aria-busy="true">
        <div className="kern-content-state">
          <LoadingState label="Opening workspace" />
        </div>
      </div>
    );
  }

  return children;
}
