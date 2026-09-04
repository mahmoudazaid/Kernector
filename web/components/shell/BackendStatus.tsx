"use client";

import { useEffect, useState } from "react";
import {
  getHealth,
  type GetHealthOptions,
  type HealthAvailability,
} from "@/lib/api/health";

export type BackendStatusProps = {
  apiBaseUrl: string;
  /** Test seam — defaults to {@link getHealth}. */
  probe?: (options: GetHealthOptions) => Promise<HealthAvailability>;
};

type StatusView =
  | { kind: "pending" }
  | { kind: "available" }
  | { kind: "unavailable"; detail: string | null };

function safeDetail(message: string | undefined): string | null {
  if (!message) {
    return null;
  }
  if (/traceback/i.test(message) || /^\s*\{/.test(message)) {
    return null;
  }
  if (/https?:\/\/\S*problems\//i.test(message)) {
    return null;
  }
  return message;
}

/**
 * Header chip showing backend reachability from ``GET /health``.
 *
 * Receives ``apiBaseUrl`` from the server layout — never calls ``loadPublicEnv``.
 */
export function BackendStatus({
  apiBaseUrl,
  probe = getHealth,
}: BackendStatusProps) {
  const [view, setView] = useState<StatusView>({ kind: "pending" });

  useEffect(() => {
    const controller = new AbortController();
    let active = true;

    void probe({ baseUrl: apiBaseUrl, signal: controller.signal })
      .then((result) => {
        if (!active) {
          return;
        }
        if (result.available) {
          setView({ kind: "available" });
          return;
        }
        setView({
          kind: "unavailable",
          detail: safeDetail(result.message),
        });
      })
      .catch(() => {
        if (!active) {
          return;
        }
        setView({ kind: "unavailable", detail: null });
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [apiBaseUrl, probe]);

  const label =
    view.kind === "pending"
      ? "Checking backend"
      : view.kind === "available"
        ? "Available"
        : "Unavailable";

  return (
    <div
      className={`kern-backend-status kern-backend-status--${view.kind}`}
      role="status"
      aria-live="polite"
      title={
        view.kind === "unavailable" ? (view.detail ?? undefined) : undefined
      }
    >
      <span className="kern-backend-status-dot" aria-hidden="true" />
      <span className="kern-backend-status-label">{label}</span>
      {view.kind === "unavailable" && view.detail ? (
        <span className="kern-backend-status-detail">{view.detail}</span>
      ) : null}
    </div>
  );
}
