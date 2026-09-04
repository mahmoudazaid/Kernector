"use client";

import { useEffect, useState, startTransition } from "react";
import { Button } from "@/components/ui/Button";
import { ApiError } from "@/lib/api/errors";
import {
  getOllamaStatus,
  type GetOllamaStatusOptions,
  type OllamaStatusResponse,
} from "@/lib/api/ollama";
import {
  getRuntimeSettings,
  type GetRuntimeSettingsOptions,
  type RuntimeSettingsResponse,
} from "@/lib/api/settings";
import {
  loadRuntimeSettings,
  saveRuntimeSettings,
  type StoredRuntimeSettings,
} from "@/lib/runtime-settings-storage";

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
  ollamaBaseUrl: string;
  settings: Record<string, number>;
};

type ProbeView =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ready"; status: OllamaStatusResponse }
  | { kind: "error" }
  | { kind: "unconfigured" };

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
    ollamaBaseUrl: catalog.ollama.default_base_url ?? "",
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

function persist(selection: SelectionState): void {
  saveRuntimeSettings({
    provider: selection.provider,
    model: selection.model,
    ollamaBaseUrl: selection.ollamaBaseUrl,
    settings: selection.settings,
  });
}

/**
 * Streamlit-parity provider/model/settings controls with client-local persistence.
 */
export function SettingsPanel({
  apiBaseUrl,
  loadCatalog = getRuntimeSettings,
  probeOllama = getOllamaStatus,
}: SettingsPanelProps) {
  const [catalogView, setCatalogView] = useState<CatalogView>({
    kind: "loading",
  });
  const [selection, setSelection] = useState<SelectionState | null>(null);
  const [probeView, setProbeView] = useState<ProbeView>({ kind: "idle" });
  const [probeNonce, setProbeNonce] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setCatalogView({ kind: "loading" });

    void loadCatalog({ baseUrl: apiBaseUrl, signal: controller.signal })
      .then((catalog) => {
        if (!active) {
          return;
        }
        const next = defaultsFromCatalog(catalog, loadRuntimeSettings());
        setSelection(next);
        persist(next);
        setCatalogView({ kind: "ready", catalog });
      })
      .catch(() => {
        if (!active) {
          return;
        }
        setCatalogView({
          kind: "error",
          message: "Settings catalog unavailable.",
        });
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [apiBaseUrl, loadCatalog]);

  const provider = selection?.provider;

  useEffect(() => {
    if (provider !== "ollama") {
      setProbeView({ kind: "idle" });
      return;
    }

    const controller = new AbortController();
    let active = true;
    setProbeView({ kind: "loading" });
    void probeOllama({
      baseUrl: apiBaseUrl,
      signal: controller.signal,
    })
      .then((status) => {
        if (!active) {
          return;
        }
        startTransition(() => {
          setProbeView({ kind: "ready", status });
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
              persist(next);
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
          setProbeView({ kind: "unconfigured" });
          return;
        }
        setProbeView({ kind: "error" });
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
      persist(next);
      return next;
    });
  }

  if (catalogView.kind === "loading") {
    return (
      <div className="kern-settings" aria-busy="true">
        <h1>Settings</h1>
        <p className="kern-settings-lead">Loading provider catalog…</p>
      </div>
    );
  }

  if (catalogView.kind === "error" || !selection) {
    return (
      <div className="kern-settings" role="alert">
        <h1>Settings</h1>
        <p className="kern-settings-lead">
          {catalogView.kind === "error"
            ? catalogView.message
            : "Settings catalog unavailable."}
        </p>
      </div>
    );
  }

  const { catalog } = catalogView;
  const modelDefs = catalog.model_settings.filter((def) =>
    def.providers.includes(selection.provider),
  );
  const openrouterModels = catalog.openrouter.models;
  const ollamaModels =
    probeView.kind === "ready" ? probeView.status.models : [];
  const ollamaReachable =
    probeView.kind === "ready" ? probeView.status.reachable : null;

  return (
    <div className="kern-settings">
      <h1>Settings</h1>
      <p className="kern-settings-lead">
        Configure the provider and model used for grounded chat. Selections stay
        in this browser until Chat uses them.
      </p>

      <fieldset className="kern-settings-fieldset">
        <legend>Provider</legend>
        <div className="kern-settings-radios" role="radiogroup" aria-label="Provider">
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
                    ollamaBaseUrl: catalog.ollama.default_base_url ?? "",
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

          {probeView.kind === "loading" ? (
            <p className="kern-settings-hint">Checking Ollama…</p>
          ) : null}

          {probeView.kind === "unconfigured" ? (
            <div
              className="kern-settings-callout kern-settings-callout--error"
              role="alert"
            >
              <p>
                Ollama base URL is not configured on the server. Set{" "}
                <code>OLLAMA_BASE_URL</code>, then reload this page.
              </p>
            </div>
          ) : null}

          {probeView.kind === "error" ? (
            <div
              className="kern-settings-callout kern-settings-callout--error"
              role="alert"
            >
              <p>Could not check Ollama. Enter a model name manually, or retry.</p>
              <Button
                variant="secondary"
                onClick={() => setProbeNonce((nonce) => nonce + 1)}
              >
                Retry
              </Button>
            </div>
          ) : null}

          {ollamaReachable === false ? (
            <div className="kern-settings-callout kern-settings-callout--error" role="alert">
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
                <code>ollama pull</code> only works after Ollama is installed. If
                you see <code>command not found</code>, finish step 1 first.
              </p>
              <Button
                variant="secondary"
                onClick={() => setProbeNonce((nonce) => nonce + 1)}
              >
                Retry
              </Button>
            </div>
          ) : null}

          {ollamaReachable === true && ollamaModels.length === 0 ? (
            <div className="kern-settings-callout kern-settings-callout--warn" role="status">
              <p>Ollama is running, but no models are installed yet.</p>
              <p>
                In a terminal, run: <code>ollama pull llama3.2</code>, then
                refresh.
              </p>
              <Button
                variant="secondary"
                onClick={() => setProbeNonce((nonce) => nonce + 1)}
              >
                Retry
              </Button>
            </div>
          ) : null}

          {ollamaReachable === true && ollamaModels.length > 0 ? (
            <>
              <div className="kern-settings-field">
                <label htmlFor="ollama-model">Ollama model</label>
                <select
                  id="ollama-model"
                  className="kern-settings-input"
                  value={
                    ollamaModels.includes(selection.model)
                      ? selection.model
                      : ollamaModels[0]
                  }
                  onChange={(event) =>
                    updateSelection({ model: event.target.value })
                  }
                >
                  {ollamaModels.map((model) => (
                    <option key={model} value={model}>
                      {model}
                    </option>
                  ))}
                </select>
              </div>
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
            <div className="kern-settings-field">
              <label htmlFor="openrouter-model">OpenRouter model</label>
              <select
                id="openrouter-model"
                className="kern-settings-input"
                value={selection.model}
                onChange={(event) =>
                  updateSelection({ model: event.target.value })
                }
              >
                {openrouterModels.map((model) => (
                  <option key={model} value={model}>
                    {model}
                  </option>
                ))}
              </select>
            </div>
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
              <p className="kern-settings-hint">No OpenRouter models available</p>
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

      <p className="kern-settings-hint">
        General grounded chat over ingested documents.
      </p>
    </div>
  );
}
