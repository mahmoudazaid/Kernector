"use client";

import {
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
  startTransition,
  type ReactNode,
} from "react";
import { LoadingState } from "@/components/states/LoadingState";
import { Button } from "@/components/ui/Button";
import { SoftSelect } from "@/components/ui/SoftSelect";
import { ApiError } from "@/lib/api/errors";
import {
  getOllamaStatus,
  type GetOllamaStatusOptions,
  type OllamaStatusResponse,
} from "@/lib/api/ollama";
import type {
  GetRuntimeSettingsOptions,
  RuntimeSettingsResponse,
} from "@/lib/api/settings";
import {
  loadRuntimeSettings,
  saveRuntimeSettings,
  type StoredRuntimeSettings,
} from "@/lib/settings/runtime-settings-storage";
import {
  SETTINGS_CATALOG_UNAVAILABLE,
  useRuntimeCatalog,
} from "@/lib/settings/use-runtime-catalog";
import { putPreferencesRequest } from "@/lib/api/auth";
import {
  getAuthSession,
  setAuthPreferences,
  subscribeAuthSession,
} from "@/lib/auth/session-store";

const PROVIDER_LABELS: Record<string, string> = {
  openrouter: "OpenRouter",
  ollama: "Ollama",
};

export type SettingsPanelProps = {
  apiBaseUrl: string;
  loadCatalog?: (
    options: GetRuntimeSettingsOptions,
  ) => Promise<RuntimeSettingsResponse>;
  probeOllama?: (
    options: GetOllamaStatusOptions,
  ) => Promise<OllamaStatusResponse>;
};

type CatalogView =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; catalog: RuntimeSettingsResponse };

type SelectionState = {
  provider: string;
  model: string;
  settings: Record<string, number>;
};

type ProbeOutcome =
  | { kind: "idle" }
  | { kind: "ready"; status: OllamaStatusResponse }
  | { kind: "error" }
  | { kind: "unconfigured" };

function ProbeCallout({
  tone = "error",
  onRetry,
  retryDisabled = false,
  retryLabel = "Retry",
  children,
}: {
  tone?: "error" | "warn";
  onRetry?: () => void;
  retryDisabled?: boolean;
  retryLabel?: string;
  children: ReactNode;
}) {
  return (
    <div className={`kern-settings-callout kern-settings-callout--${tone}`}>
      <div role="status">{children}</div>
      {onRetry ? (
        <Button variant="secondary" disabled={retryDisabled} onClick={onRetry}>
          {retryLabel}
        </Button>
      ) : null}
    </div>
  );
}

function nonBlank(value: string | undefined | null): string | undefined {
  if (typeof value !== "string") {
    return undefined;
  }
  const trimmed = value.trim();
  return trimmed ? trimmed : undefined;
}

function clampSetting(
  def: { min_value: number; max_value: number },
  value: number,
): number {
  return Math.min(def.max_value, Math.max(def.min_value, value));
}

function resolveOpenRouterModel(
  catalog: RuntimeSettingsResponse,
  preferred: string | undefined,
): string {
  const models = catalog.openrouter.models;
  if (models.length === 0) {
    return preferred ?? "";
  }
  if (preferred && models.includes(preferred)) {
    return preferred;
  }
  const catalogDefault = nonBlank(catalog.openrouter.default_model);
  if (catalogDefault && models.includes(catalogDefault)) {
    return catalogDefault;
  }
  return models[0] ?? "";
}

function resolveProvider(
  catalog: RuntimeSettingsResponse,
  storedProvider: string | undefined,
): string {
  if (storedProvider && catalog.providers.includes(storedProvider)) {
    return storedProvider;
  }
  if (catalog.providers.includes(catalog.default_provider)) {
    return catalog.default_provider;
  }
  return catalog.providers[0] ?? catalog.default_provider;
}

function defaultsFromCatalog(
  catalog: RuntimeSettingsResponse,
  stored: StoredRuntimeSettings | null,
): SelectionState {
  const provider = resolveProvider(catalog, stored?.provider);
  const storedModel = nonBlank(stored?.model);
  const ollamaDefault = catalog.ollama.default_model ?? "";

  let model: string;
  if (provider === "ollama") {
    model = storedModel ?? ollamaDefault;
  } else {
    model = resolveOpenRouterModel(catalog, storedModel);
  }

  return {
    provider,
    model,
    settings: Object.fromEntries(
      catalog.model_settings
        .filter((def) => def.providers.includes(provider))
        .map((def) => {
          const raw = stored?.settings?.[def.key];
          return [
            def.key,
            typeof raw === "number" ? clampSetting(def, raw) : def.default,
          ];
        }),
    ),
  };
}

function persistLocal(selection: SelectionState, signedIn: boolean): void {
  if (!signedIn) {
    saveRuntimeSettings({
      provider: selection.provider,
      model: selection.model,
      settings: selection.settings,
    });
    return;
  }
  // Signed-in: never write provider/model to the anonymous key (ADR 0013 §8).
  const existing = loadRuntimeSettings();
  if (existing) {
    saveRuntimeSettings({
      provider: existing.provider,
      model: existing.model,
      settings: selection.settings,
    });
  }
}

/**
 * Provider/model/settings controls with client-local persistence.
 */
export function SettingsPanel({
  apiBaseUrl,
  loadCatalog,
  probeOllama = getOllamaStatus,
}: SettingsPanelProps) {
  const {
    catalog,
    error: catalogError,
    loading: catalogLoading,
    reload,
  } = useRuntimeCatalog(apiBaseUrl, loadCatalog);
  const auth = useSyncExternalStore(
    subscribeAuthSession,
    getAuthSession,
    getAuthSession,
  );
  const [selection, setSelection] = useState<SelectionState | null>(null);
  const [selectionForCatalog, setSelectionForCatalog] =
    useState<RuntimeSettingsResponse | null>(null);
  const [seededForAuthGen, setSeededForAuthGen] = useState<number | null>(null);
  const [prefsError, setPrefsError] = useState<string | null>(null);
  const [probeOutcome, setProbeOutcome] = useState<ProbeOutcome>({
    kind: "idle",
  });
  const [probeLoading, setProbeLoading] = useState(false);
  const [probeNonce, setProbeNonce] = useState(0);
  const putSeqRef = useRef(0);

  const prefsReady =
    auth.user === null || auth.preferencesStatus === "ready";
  const needsReseed =
    catalog !== null &&
    (catalog !== selectionForCatalog ||
      (auth.user !== null && seededForAuthGen !== auth.generation));

  if (needsReseed && prefsReady) {
    if (catalog) {
      const authPrefs = auth.preferences;
      const storedLocal = loadRuntimeSettings();
      const storedFromAuth =
        auth.user !== null &&
        authPrefs !== null &&
        authPrefs.usable &&
        authPrefs.provider !== null &&
        authPrefs.model !== null
          ? {
              provider: authPrefs.provider,
              model: authPrefs.model,
              settings: storedLocal?.settings ?? {},
            }
          : auth.user === null
            ? storedLocal
            : storedLocal
              ? {
                  provider: storedLocal.provider,
                  model: storedLocal.model,
                  settings: storedLocal.settings,
                }
              : null;
      // Missing/stale auth prefs: fall back to catalog defaults, not localStorage pair.
      const seedSource =
        auth.user !== null &&
        (authPrefs === null ||
          !authPrefs.usable ||
          authPrefs.provider === null ||
          authPrefs.model === null)
          ? {
              provider: undefined,
              model: undefined,
              settings: storedLocal?.settings ?? {},
            }
          : storedFromAuth;
      const next = defaultsFromCatalog(
        catalog,
        seedSource
          ? {
              provider: seedSource.provider ?? "",
              model: seedSource.model ?? "",
              settings: seedSource.settings ?? {},
            }
          : null,
      );
      setSelection(next);
      setSelectionForCatalog(catalog);
      setSeededForAuthGen(auth.generation);
      // Seed only — never PUT server preferences without a user action.
      persistLocal(next, auth.user !== null);
    } else {
      setSelection(null);
      setSelectionForCatalog(null);
    }
  }

  const catalogView: CatalogView = catalogError
    ? { kind: "error", message: catalogError }
    : catalogLoading
      ? { kind: "loading" }
      : catalog
        ? { kind: "ready", catalog }
        : { kind: "loading" };

  const provider = selection?.provider;

  useEffect(() => {
    if (provider !== "ollama") {
      setProbeOutcome({ kind: "idle" });
      setProbeLoading(false);
      return;
    }

    const controller = new AbortController();
    let active = true;
    setProbeLoading(true);
    void probeOllama({
      baseUrl: apiBaseUrl,
      signal: controller.signal,
    })
      .then((status) => {
        if (!active) {
          return;
        }
        startTransition(() => {
          setProbeOutcome({ kind: "ready", status });
          setSelection((current) => {
            if (!current || current.provider !== "ollama") {
              return current;
            }
            if (
              status.reachable &&
              status.models.length > 0 &&
              !status.models.includes(current.model)
            ) {
              const next = { ...current, model: status.models[0] ?? "" };
              persistLocal(next, getAuthSession().user !== null);
              return next;
            }
            return current;
          });
        });
      })
      .catch((error: unknown) => {
        if (!active) {
          return;
        }
        if (
          error instanceof ApiError &&
          (error.code === "ollama_unconfigured" || error.status === 409)
        ) {
          setProbeOutcome({ kind: "unconfigured" });
          return;
        }
        setProbeOutcome({ kind: "error" });
      })
      .finally(() => {
        if (active) {
          setProbeLoading(false);
        }
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [apiBaseUrl, probeOllama, provider, probeNonce]);

  function updateSelection(patch: Partial<SelectionState>): void {
    setSelection((current) => {
      if (!current) {
        return current;
      }
      const next = { ...current, ...patch };
      const signedIn = getAuthSession().user !== null;
      persistLocal(next, signedIn);

      const providerModelChanged =
        (patch.provider !== undefined && patch.provider !== current.provider) ||
        (patch.model !== undefined && patch.model !== current.model);

      if (signedIn && providerModelChanged) {
        const session = getAuthSession();
        if (session.csrfToken) {
          const seq = ++putSeqRef.current;
          const generation = session.generation;
          setPrefsError(null);
          void putPreferencesRequest(
            session.csrfToken,
            next.provider,
            next.model,
          )
            .then((prefs) => {
              if (putSeqRef.current !== seq) {
                return;
              }
              setAuthPreferences(prefs, { generation, status: "ready" });
            })
            .catch(() => {
              if (putSeqRef.current !== seq) {
                return;
              }
              setPrefsError(
                "Could not save provider/model preferences. Try again.",
              );
            });
        }
      }
      return next;
    });
  }

  function retryProbe(): void {
    setProbeNonce((nonce) => nonce + 1);
  }

  if (catalogView.kind === "loading" || !prefsReady) {
    return (
      <div className="kern-settings" aria-busy="true">
        <h1>Settings</h1>
        <div className="kern-content-state">
          <LoadingState label="Loading settings" />
        </div>
      </div>
    );
  }

  if (catalogView.kind === "error" || !selection || !catalog) {
    return (
      <div className="kern-settings" role="alert">
        <h1>Settings</h1>
        <p className="kern-settings-lead">
          {catalogView.kind === "error"
            ? catalogView.message
            : SETTINGS_CATALOG_UNAVAILABLE}
        </p>
        <Button
          variant="secondary"
          disabled={catalogLoading}
          onClick={() => reload()}
        >
          {catalogLoading ? "Checking…" : "Retry"}
        </Button>
      </div>
    );
  }

  const modelDefs = catalog.model_settings.filter((def) =>
    def.providers.includes(selection.provider),
  );
  const openrouterModels = catalog.openrouter.models;
  const ollamaModels =
    probeOutcome.kind === "ready" ? probeOutcome.status.models : [];
  const ollamaReachable =
    probeOutcome.kind === "ready" ? probeOutcome.status.reachable : null;
  const showInitialProbeHint =
    selection.provider === "ollama" &&
    probeLoading &&
    probeOutcome.kind === "idle";

  return (
    <div className="kern-settings">
      <h1>Settings</h1>
      <p className="kern-settings-lead">
        Configure the provider and model used for grounded chat. Selections stay
        in this browser until Chat uses them.
      </p>
      {prefsError ? (
        <p className="kern-settings-callout kern-settings-callout--error" role="alert">
          {prefsError}
        </p>
      ) : null}

      <fieldset className="kern-settings-fieldset">
        <legend>Provider</legend>
        <div
          className="kern-settings-radios"
          role="radiogroup"
          aria-label="Provider"
        >
          {catalog.providers.map((provider) => (
            <label key={provider} className="kern-settings-radio">
              <input
                type="radio"
                name="provider"
                value={provider}
                checked={selection.provider === provider}
                onChange={() => {
                  const nextSettings: Record<string, number> = {};
                  for (const def of catalog.model_settings) {
                    if (def.providers.includes(provider)) {
                      const raw = selection.settings[def.key];
                      nextSettings[def.key] =
                        typeof raw === "number"
                          ? clampSetting(def, raw)
                          : def.default;
                    }
                  }
                  const nextModel =
                    provider === "ollama"
                      ? (catalog.ollama.default_model ?? "")
                      : resolveOpenRouterModel(catalog, undefined);
                  updateSelection({
                    provider,
                    model: nextModel,
                    settings: nextSettings,
                  });
                }}
              />
              <span>{PROVIDER_LABELS[provider] ?? provider}</span>
            </label>
          ))}
        </div>
      </fieldset>

      {selection.provider === "ollama" ? (
        <div className="kern-settings-stack">
          <div className="kern-settings-field">
            <label htmlFor="ollama-base-url">Ollama base URL</label>
            <input
              id="ollama-base-url"
              className="kern-settings-input"
              type="url"
              readOnly
              value={catalog.ollama.default_base_url ?? ""}
            />
            <p className="kern-settings-hint">
              Set via <code>OLLAMA_BASE_URL</code> on the server.
            </p>
          </div>

          {showInitialProbeHint ? (
            <p className="kern-settings-hint">Checking Ollama…</p>
          ) : null}

          {probeOutcome.kind === "unconfigured" ? (
            <ProbeCallout>
              <p>
                Ollama base URL is not configured on the server. Set{" "}
                <code>OLLAMA_BASE_URL</code>, then reload this page.
              </p>
            </ProbeCallout>
          ) : null}

          {probeOutcome.kind === "error" ? (
            <ProbeCallout
              onRetry={retryProbe}
              retryDisabled={probeLoading}
              retryLabel={probeLoading ? "Checking…" : "Retry"}
            >
              <p>
                Could not check Ollama. Enter a model name manually, or retry.
              </p>
            </ProbeCallout>
          ) : null}

          {ollamaReachable === false ? (
            <ProbeCallout
              onRetry={retryProbe}
              retryDisabled={probeLoading}
              retryLabel={probeLoading ? "Checking…" : "Retry"}
            >
              <p>Ollama is not reachable.</p>
              <ol>
                <li>
                  Install Ollama from{" "}
                  <a href="https://ollama.com/download">ollama.com/download</a>
                </li>
                <li>Open the Ollama app (starts the local server)</li>
                <li>
                  In a terminal, run: <code>ollama pull llama3.2</code>
                </li>
                <li>Refresh this page</li>
              </ol>
              <p className="kern-settings-hint">
                <code>ollama pull</code> only works after Ollama is installed.
                If you see <code>command not found</code>, finish step 1 first.
              </p>
            </ProbeCallout>
          ) : null}

          {ollamaReachable === true && ollamaModels.length === 0 ? (
            <ProbeCallout
              tone="warn"
              onRetry={retryProbe}
              retryDisabled={probeLoading}
              retryLabel={probeLoading ? "Checking…" : "Retry"}
            >
              <p>Ollama is running, but no models are installed yet.</p>
              <p>
                In a terminal, run: <code>ollama pull llama3.2</code>, then
                refresh.
              </p>
            </ProbeCallout>
          ) : null}

          {ollamaReachable === true && ollamaModels.length > 0 ? (
            <>
              <SoftSelect
                id="ollama-model"
                label="Ollama model"
                value={
                  ollamaModels.includes(selection.model)
                    ? selection.model
                    : ollamaModels[0]
                }
                options={ollamaModels}
                onChange={(model) => updateSelection({ model })}
              />
              <p className="kern-settings-hint">
                Ollama connected · local, slower, no API cost.
              </p>
            </>
          ) : (
            <div className="kern-settings-field">
              <label htmlFor="ollama-model-text">Ollama model</label>
              <input
                id="ollama-model-text"
                className="kern-settings-input"
                type="text"
                value={selection.model}
                onChange={(event) =>
                  updateSelection({ model: event.target.value })
                }
              />
            </div>
          )}
        </div>
      ) : (
        <div className="kern-settings-stack">
          {openrouterModels.length > 0 ? (
            <SoftSelect
              id="openrouter-model"
              label="OpenRouter model"
              value={selection.model}
              options={openrouterModels}
              onChange={(model) => updateSelection({ model })}
            />
          ) : (
            <>
              <div className="kern-settings-field">
                <label htmlFor="openrouter-model-text">OpenRouter model</label>
                <input
                  id="openrouter-model-text"
                  className="kern-settings-input"
                  type="text"
                  value={selection.model}
                  onChange={(event) =>
                    updateSelection({ model: event.target.value })
                  }
                />
              </div>
              <p className="kern-settings-hint">
                No OpenRouter models available
              </p>
            </>
          )}
        </div>
      )}

      <details className="kern-settings-details" open>
        <summary>Model Settings</summary>
        <p className="kern-settings-hint">
          Defaults are safe. Change only what you need.
        </p>
        <div className="kern-settings-stack">
          {modelDefs.map((def) => {
            const current = selection.settings[def.key] ?? def.default;
            const isSlider = def.widget === "slider";
            const inputId = `setting-${def.key}`;
            const helpId = `setting-help-${def.key}`;
            return (
              <div key={def.key} className="kern-settings-field">
                <label htmlFor={inputId}>{def.label}</label>
                <p id={helpId} className="kern-settings-help">
                  {def.help}
                </p>
                <input
                  id={inputId}
                  className="kern-settings-input"
                  type={isSlider ? "range" : "number"}
                  min={def.min_value}
                  max={def.max_value}
                  step={def.step}
                  value={current}
                  aria-describedby={helpId}
                  onChange={(event) => {
                    const raw = event.target.value;
                    if (raw === "") {
                      return;
                    }
                    const value = Number(raw);
                    if (!Number.isFinite(value)) {
                      return;
                    }
                    updateSelection({
                      settings: {
                        ...selection.settings,
                        [def.key]: clampSetting(def, value),
                      },
                    });
                  }}
                />
                {isSlider ? (
                  <span className="kern-settings-help" aria-hidden="true">
                    {current}
                  </span>
                ) : null}
              </div>
            );
          })}
        </div>
      </details>
    </div>
  );
}
