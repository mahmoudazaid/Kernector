"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  getRuntimeSettings,
  type GetRuntimeSettingsOptions,
  type RuntimeSettingsResponse,
} from "@/lib/api/settings";

export const SETTINGS_CATALOG_UNAVAILABLE = "Settings catalog unavailable.";

export type RuntimeCatalogLoader = (
  options: GetRuntimeSettingsOptions,
) => Promise<RuntimeSettingsResponse>;

export type RuntimeCatalogState = {
  catalog: RuntimeSettingsResponse | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
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
  const [reloadNonce, setReloadNonce] = useState(0);
  const loadRef = useRef(loadCatalog ?? getRuntimeSettings);
  const prevUrlRef = useRef(apiBaseUrl);
  loadRef.current = loadCatalog ?? getRuntimeSettings;

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    const resetCatalog = prevUrlRef.current !== apiBaseUrl;
    prevUrlRef.current = apiBaseUrl;
    if (resetCatalog) {
      setCatalog(null);
    }
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
        if (resetCatalog) {
          setCatalog(null);
        }
        setError(SETTINGS_CATALOG_UNAVAILABLE);
        setLoading(false);
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [apiBaseUrl, reloadNonce]);

  const reload = useCallback(() => {
    setReloadNonce((nonce) => nonce + 1);
  }, []);

  return { catalog, error, loading, reload };
}
