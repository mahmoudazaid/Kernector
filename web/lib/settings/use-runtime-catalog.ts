"use client";

import { useEffect, useRef, useState } from "react";
import {
  getRuntimeSettings,
  type GetRuntimeSettingsOptions,
  type RuntimeSettingsResponse,
} from "@/lib/api/settings";

export type RuntimeCatalogLoader = (
  options: GetRuntimeSettingsOptions,
) => Promise<RuntimeSettingsResponse>;

export type RuntimeCatalogState = {
  catalog: RuntimeSettingsResponse | null;
  error: string | null;
  loading: boolean;
};

/**
 * Shared GET /api/v1/settings loader for ChatPanel, SettingsPanel, and
 * DocumentsPanel.
 *
 * Owns AbortController cleanup, resets state when `apiBaseUrl` changes, and
 * reads the latest loader via a ref so inline prop functions do not refetch.
 */
export function useRuntimeCatalog(
  apiBaseUrl: string,
  loadCatalog?: RuntimeCatalogLoader,
): RuntimeCatalogState {
  const [catalog, setCatalog] = useState<RuntimeSettingsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const loadRef = useRef(loadCatalog ?? getRuntimeSettings);
  loadRef.current = loadCatalog ?? getRuntimeSettings;

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setCatalog(null);
    setError(null);
    setLoading(true);

    void loadRef
      .current({ baseUrl: apiBaseUrl, signal: controller.signal })
      .then((result) => {
        if (!active) {
          return;
        }
        setCatalog(result);
        setError(null);
        setLoading(false);
      })
      .catch(() => {
        if (!active || controller.signal.aborted) {
          return;
        }
        setCatalog(null);
        setError("Settings catalog unavailable.");
        setLoading(false);
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [apiBaseUrl]);

  return { catalog, error, loading };
}
