import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SettingsPanel } from "@/components/settings/SettingsPanel";
import type { RuntimeSettingsResponse } from "@/lib/api/settings";
import {
  CHAT_MESSAGES_STORAGE_KEY,
  loadRuntimeSettings,
  RUNTIME_SETTINGS_STORAGE_KEY,
} from "@/lib/settings/runtime-settings-storage";
import {
  ACTIVE_SESSION_STORAGE_KEY,
  loadActiveSession,
  saveActiveSession,
} from "@/lib/session/active-session";

const CATALOG: RuntimeSettingsResponse = {
  providers: ["openrouter", "ollama"],
  default_provider: "openrouter",
  openrouter: {
    models: ["openai/gpt-4o-mini", "anthropic/claude-3.5"],
    default_model: "openai/gpt-4o-mini",
  },
  ollama: {
    default_base_url: "http://127.0.0.1:11434",
    default_model: "llama3.2",
  },
  model_settings: [
    {
      key: "temperature",
      label: "Temperature",
      widget: "slider",
      default: 0.3,
      min_value: 0,
      max_value: 2,
      step: 0.1,
      help: "Higher is more creative.",
      providers: ["openrouter", "ollama"],
    },
    {
      key: "max_tokens",
      label: "Max Tokens",
      widget: "number",
      default: 1000,
      min_value: 100,
      max_value: 10000,
      step: 100,
      help: "Upper bound on reply length.",
      providers: ["openrouter", "ollama"],
    },
    {
      key: "top_p",
      label: "Top P",
      widget: "slider",
      default: 1,
      min_value: 0,
      max_value: 1,
      step: 0.1,
      help: "Nucleus sampling.",
      providers: ["openrouter", "ollama"],
    },
  ],
  enabled_packs: ["software-delivery"],
  constraints: {
    max_input_length: 10000,
    max_upload_bytes: 5242880,
    supported_upload_suffixes: [".markdown", ".md", ".pdf", ".txt"],
  },
};

describe("SettingsPanel", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("shows the brand loader while the catalog is loading", () => {
    render(
      <SettingsPanel
        apiBaseUrl="http://127.0.0.1:8000"
        loadCatalog={() => new Promise(() => {})}
      />,
    );

    expect(screen.getByRole("heading", { name: "Settings" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/loading settings/i);
    expect(screen.queryByText(/loading provider catalog/i)).toBeNull();
  });

  it("renders OpenRouter happy path from the catalog", async () => {
    render(
      <SettingsPanel
        apiBaseUrl="http://127.0.0.1:8000"
        loadCatalog={async () => CATALOG}
        probeOllama={async () => ({ reachable: false, models: [] })}
      />,
    );

    expect(
      await screen.findByRole("heading", { level: 1, name: "Settings" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /OpenRouter/i })).toBeChecked();
    expect(screen.getByLabelText(/OpenRouter model/i)).toHaveTextContent(
      "openai/gpt-4o-mini",
    );
    expect(screen.getByLabelText(/Temperature/i)).toHaveAttribute(
      "type",
      "range",
    );
    expect(screen.getByLabelText(/Temperature/i)).toHaveValue("0.3");
    expect(screen.getByLabelText(/Max Tokens/i)).toHaveAttribute(
      "type",
      "number",
    );

    await waitFor(() => {
      expect(loadRuntimeSettings()?.provider).toBe("openrouter");
      expect(loadRuntimeSettings()?.model).toBe("openai/gpt-4o-mini");
    });
  });

  it("replaces a stale stored OpenRouter model with the catalog default", async () => {
    localStorage.setItem(
      "kernector:runtime-settings:v1",
      JSON.stringify({
        provider: "openrouter",
        model: "z/removed-model",
        settings: { temperature: 0.3, max_tokens: 1000, top_p: 1 },
      }),
    );

    render(
      <SettingsPanel
        apiBaseUrl="http://127.0.0.1:8000"
        loadCatalog={async () => CATALOG}
      />,
    );

    expect(await screen.findByLabelText(/OpenRouter model/i)).toHaveTextContent(
      "openai/gpt-4o-mini",
    );
    await waitFor(() => {
      expect(loadRuntimeSettings()?.model).toBe("openai/gpt-4o-mini");
    });
  });

  it("shows probe error guidance when the Ollama check fails", async () => {
    const user = userEvent.setup();
    render(
      <SettingsPanel
        apiBaseUrl="http://127.0.0.1:8000"
        loadCatalog={async () => CATALOG}
        probeOllama={async () => {
          throw new Error("timeout");
        }}
      />,
    );

    await screen.findByRole("radio", { name: /Ollama/i });
    await user.click(screen.getByRole("radio", { name: /Ollama/i }));

    expect(
      await screen.findByText(/Could not check Ollama/i),
    ).toBeInTheDocument();
    const retry = screen.getByRole("button", { name: /^Retry$/i });
    expect(retry).toBeInTheDocument();
    expect(retry.closest("[role='status']")).toBeNull();
  });

  it("shows unconfigured guidance when the server has no Ollama URL", async () => {
    const user = userEvent.setup();
    const { ApiError } = await import("@/lib/api/errors");
    render(
      <SettingsPanel
        apiBaseUrl="http://127.0.0.1:8000"
        loadCatalog={async () => CATALOG}
        probeOllama={async () => {
          throw new ApiError({
            status: 409,
            title: "Ollama not configured",
            detail: "Ollama base URL is not configured on the server.",
            code: "ollama_unconfigured",
          });
        }}
      />,
    );

    await screen.findByRole("radio", { name: /Ollama/i });
    await user.click(screen.getByRole("radio", { name: /Ollama/i }));

    expect(
      await screen.findByText(/not configured on the server/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^Retry$/i }),
    ).not.toBeInTheDocument();
  });

  it("keeps the Ollama base URL read-only from the catalog", async () => {
    const user = userEvent.setup();
    render(
      <SettingsPanel
        apiBaseUrl="http://127.0.0.1:8000"
        loadCatalog={async () => CATALOG}
        probeOllama={async () => ({ reachable: false, models: [] })}
      />,
    );

    await screen.findByRole("radio", { name: /Ollama/i });
    await user.click(screen.getByRole("radio", { name: /Ollama/i }));

    const url = await screen.findByLabelText(/Ollama base URL/i);
    expect(url).toHaveAttribute("readonly");
    expect(url).toHaveValue("http://127.0.0.1:11434");
    await waitFor(() => {
      expect(loadRuntimeSettings()).not.toHaveProperty("ollamaBaseUrl");
      expect(loadRuntimeSettings()?.provider).toBe("ollama");
    });
  });

  it("clamps out-of-range stored settings on hydrate", async () => {
    localStorage.setItem(
      "kernector:runtime-settings:v1",
      JSON.stringify({
        provider: "openrouter",
        model: "openai/gpt-4o-mini",
        settings: { temperature: 99, max_tokens: -5, top_p: 1 },
      }),
    );

    render(
      <SettingsPanel
        apiBaseUrl="http://127.0.0.1:8000"
        loadCatalog={async () => CATALOG}
      />,
    );

    expect(await screen.findByLabelText(/^Temperature$/i)).toHaveValue("2");
    expect(screen.getByLabelText(/^Max Tokens$/i)).toHaveValue(100);
    await waitFor(() => {
      expect(loadRuntimeSettings()?.settings).toEqual({
        temperature: 2,
        max_tokens: 100,
        top_p: 1,
      });
    });
  });

  it("falls back when catalog default_model is not in the models list", async () => {
    const catalog: RuntimeSettingsResponse = {
      ...CATALOG,
      openrouter: {
        models: ["a/one", "b/two"],
        default_model: "z/not-in-list",
      },
    };

    render(
      <SettingsPanel
        apiBaseUrl="http://127.0.0.1:8000"
        loadCatalog={async () => catalog}
      />,
    );

    expect(await screen.findByLabelText(/OpenRouter model/i)).toHaveTextContent(
      "a/one",
    );
    await waitFor(() => {
      expect(loadRuntimeSettings()?.model).toBe("a/one");
    });
  });

  it("clamps model settings and ignores empty clears", async () => {
    const user = userEvent.setup();
    render(
      <SettingsPanel
        apiBaseUrl="http://127.0.0.1:8000"
        loadCatalog={async () => CATALOG}
      />,
    );

    const maxTokens = await screen.findByLabelText(/Max Tokens/i);
    await user.clear(maxTokens);
    await waitFor(() => {
      expect(loadRuntimeSettings()?.settings.max_tokens).toBe(1000);
    });

    await user.clear(maxTokens);
    await user.type(maxTokens, "99999");
    await waitFor(() => {
      expect(loadRuntimeSettings()?.settings.max_tokens).toBe(10000);
    });
  });

  it("shows unreachable Ollama guidance", async () => {
    const user = userEvent.setup();
    render(
      <SettingsPanel
        apiBaseUrl="http://127.0.0.1:8000"
        loadCatalog={async () => CATALOG}
        probeOllama={async () => ({ reachable: false, models: [] })}
      />,
    );

    await screen.findByRole("radio", { name: /Ollama/i });
    await user.click(screen.getByRole("radio", { name: /Ollama/i }));

    expect(
      await screen.findByText(/Ollama is not reachable/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/ollama.com\/download/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^Ollama model$/i)).toHaveAttribute(
      "type",
      "text",
    );
  });

  it("shows empty-model guidance when Ollama is reachable without models", async () => {
    const user = userEvent.setup();
    render(
      <SettingsPanel
        apiBaseUrl="http://127.0.0.1:8000"
        loadCatalog={async () => CATALOG}
        probeOllama={async () => ({ reachable: true, models: [] })}
      />,
    );

    await screen.findByRole("radio", { name: /Ollama/i });
    await user.click(screen.getByRole("radio", { name: /Ollama/i }));

    expect(
      await screen.findByText(/no models are installed yet/i),
    ).toBeInTheDocument();
  });

  it("lists Ollama models when the probe succeeds", async () => {
    const user = userEvent.setup();
    render(
      <SettingsPanel
        apiBaseUrl="http://127.0.0.1:8000"
        loadCatalog={async () => CATALOG}
        probeOllama={async () => ({
          reachable: true,
          models: ["llama3.2", "mistral"],
        })}
      />,
    );

    await screen.findByRole("radio", { name: /Ollama/i });
    await user.click(screen.getByRole("radio", { name: /Ollama/i }));

    expect(await screen.findByText(/Ollama connected/i)).toBeInTheDocument();
    const trigger = screen.getByLabelText(/^Ollama model$/i);
    expect(trigger).toHaveAttribute("aria-haspopup", "listbox");
    await user.click(trigger);
    expect(screen.getByRole("option", { name: "mistral" })).toBeInTheDocument();
  });

  it("shows a safe error when the catalog fails", async () => {
    const user = userEvent.setup();
    const loadCatalog = vi
      .fn()
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce(CATALOG);

    render(
      <SettingsPanel
        apiBaseUrl="http://127.0.0.1:8000"
        loadCatalog={loadCatalog}
      />,
    );

    expect(
      await screen.findByText(/Settings catalog unavailable/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/boom|Traceback/i)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^Retry$/i }));

    expect(
      await screen.findByRole("radio", { name: /OpenRouter/i }),
    ).toBeInTheDocument();
    expect(loadCatalog).toHaveBeenCalledTimes(2);
  });

  it("leaves the active session untouched when provider/model change", async () => {
    const user = userEvent.setup();
    const session = {
      draft: "keep this draft",
      messages: [{ id: "1", role: "user" as const, content: "keep this turn" }],
      updatedAt: 1,
    };
    saveActiveSession(session);
    const sessionBefore = localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY);
    const transcriptBefore = localStorage.getItem(CHAT_MESSAGES_STORAGE_KEY);

    render(
      <SettingsPanel
        apiBaseUrl="http://127.0.0.1:8000"
        loadCatalog={async () => CATALOG}
        probeOllama={async () => ({ reachable: false, models: [] })}
      />,
    );

    await screen.findByRole("radio", { name: /Ollama/i });
    await user.click(screen.getByRole("radio", { name: /Ollama/i }));

    await waitFor(() => {
      expect(loadRuntimeSettings()?.provider).toBe("ollama");
    });

    expect(localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY)).toBe(
      sessionBefore,
    );
    expect(localStorage.getItem(CHAT_MESSAGES_STORAGE_KEY)).toBe(
      transcriptBefore,
    );
    expect(loadActiveSession()).toEqual({
      draft: session.draft,
      messages: session.messages,
      updatedAt: expect.any(Number),
    });
    expect(localStorage.getItem(RUNTIME_SETTINGS_STORAGE_KEY)).toBeTruthy();
  });
});
