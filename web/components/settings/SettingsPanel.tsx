"use client";

import { useEffect, useState, startTransition } from "react";
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
  | { kind: "error" };

function nonBlank(value: string | undefined | null): string | undefined {
  if (typeof value !== "string") {
    return undefined;
  }
  const trimmed = value.trim();
  return trimmed ? trimmed : undefined;
}

function defaultsFromCatalog(
  catalog: RuntimeSettingsResponse,
  stored: StoredRuntimeSettings | null,
): SelectionState {
  const provider =
    stored?.provider && catalog.providers.includes(stored.provider)
      ? stored.provider
      : catalog.default_provider;

  const openrouterDefault =
    catalog.openrouter.default_model ?? catalog.openrouter.models[0] ?? "";
  const ollamaDefault = catalog.ollama.default_model ?? "";
  const storedModel = nonBlank(stored?.model);

  let model: string;
  if (provider === "ollama") {
    model = storedModel ?? ollamaDefault;
  } else if (catalog.openrouter.models.length > 0) {
    model =
      storedModel && catalog.openrouter.models.includes(storedModel)
        ? storedModel
        : openrouterDefault;
  } else {
    model = storedModel ?? openrouterDefault;
  }

  return {
    provider,
    model,
    ollamaBaseUrl:
      nonBlank(stored?.ollamaBaseUrl) ??
      catalog.ollama.default_base_url ??
      "",
    settings: Object.fromEntries(
      catalog.model_settings
        .filter((def) => def.providers.includes(provider))
        .map((def) => [def.key, stored?.settings?.[def.key] ?? def.default]),
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
  const ollamaBaseUrl = selection?.ollamaBaseUrl;

  useEffect(() => {
    if (provider !== "ollama") {
      setProbeView({ kind: "idle" });
      return;
    }
    const trimmed = ollamaBaseUrl?.trim() ?? "";
    if (!trimmed) {
      setProbeView({ kind: "idle" });
      return;
    }

    const controller = new AbortController();
    let active = true;
    const timer = window.setTimeout(() => {
      setProbeView({ kind: "loading" });
      void probeOllama({
        baseUrl: apiBaseUrl,
        ollamaBaseUrl: trimmed,
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
        .catch(() => {
          if (!active) {
            return;
          }
          setProbeView({ kind: "error" });
        });
    }, 250);

    return () => {
      active = false;
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [apiBaseUrl, probeOllama, provider, ollamaBaseUrl]);

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
                      nextSettings[def.key] =
                        selection.settings[def.key] ?? def.default;
                    }
                  }
                  const nextModel =
                    provider === "ollama"
                      ? (catalog.ollama.default_model ?? "")
                      : (catalog.openrouter.default_model ??
                        catalog.openrouter.models[0] ??
                        "");
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
          <label className="kern-settings-field">
            <span>Ollama base URL</span>
            <input
              className="kern-settings-input"
              type="url"
              value={selection.ollamaBaseUrl}
              onChange={(event) =>
                updateSelection({ ollamaBaseUrl: event.target.value })
              }
            />
          </label>

          {probeView.kind === "loading" ? (
            <p className="kern-settings-hint">Checking Ollama…</p>
          ) : null}

          {probeView.kind === "error" ? (
            <div
              className="kern-settings-callout kern-settings-callout--error"
              role="alert"
            >
              <p>
                Could not check Ollama. Enter a model name manually, or retry.
              </p>
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
            </div>
          ) : null}

          {ollamaReachable === true && ollamaModels.length === 0 ? (
            <div className="kern-settings-callout kern-settings-callout--warn" role="status">
              <p>Ollama is running, but no models are installed yet.</p>
              <p>
                In a terminal, run: <code>ollama pull llama3.2</code>, then
                refresh.
              </p>
            </div>
          ) : null}

          {ollamaReachable === true && ollamaModels.length > 0 ? (
            <>
              <label className="kern-settings-field">
                <span>Ollama model</span>
                <select
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
              </label>
              <p className="kern-settings-hint">
                Ollama connected · local, slower, no API cost.
              </p>
            </>
          ) : (
            <label className="kern-settings-field">
              <span>Ollama model</span>
              <input
                className="kern-settings-input"
                type="text"
                value={selection.model}
                onChange={(event) =>
                  updateSelection({ model: event.target.value })
                }
              />
            </label>
          )}
        </div>
      ) : (
        <div className="kern-settings-stack">
          {openrouterModels.length > 0 ? (
            <label className="kern-settings-field">
              <span>OpenRouter model</span>
              <select
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
            </label>
          ) : (
            <>
              <label className="kern-settings-field">
                <span>OpenRouter model</span>
                <input
                  className="kern-settings-input"
                  type="text"
                  value={selection.model}
                  onChange={(event) =>
                    updateSelection({ model: event.target.value })
                  }
                />
              </label>
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
            return (
              <label key={def.key} className="kern-settings-field">
                <span>
                  {def.label}
                  <span className="kern-settings-help">{def.help}</span>
                </span>
                <input
                  className="kern-settings-input"
                  type={isSlider ? "range" : "number"}
                  min={def.min_value}
                  max={def.max_value}
                  step={def.step}
                  value={current}
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
                        [def.key]: Math.min(
                          def.max_value,
                          Math.max(def.min_value, value),
                        ),
                      },
                    });
                  }}
                />
                {isSlider ? (
                  <span className="kern-settings-help">{current}</span>
                ) : null}
              </label>
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
