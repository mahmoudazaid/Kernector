import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { SettingsPanel } from "@/components/settings/SettingsPanel";
import type { RuntimeSettingsResponse } from "@/lib/api/settings";
import { loadRuntimeSettings } from "@/lib/runtime-settings-storage";

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
};

describe("SettingsPanel", () => {
  beforeEach(() => {
    localStorage.clear();
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
    expect(screen.getByLabelText(/OpenRouter model/i)).toHaveValue(
      "openai/gpt-4o-mini",
    );
    expect(screen.getByLabelText(/Temperature/i)).toHaveAttribute("type", "range");
    expect(screen.getByLabelText(/Temperature/i)).toHaveValue("0.3");
    expect(screen.getByLabelText(/Max Tokens/i)).toHaveAttribute("type", "number");

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
        ollamaBaseUrl: "",
        settings: { temperature: 0.3, max_tokens: 1000, top_p: 1 },
      }),
    );

    render(
      <SettingsPanel
        apiBaseUrl="http://127.0.0.1:8000"
        loadCatalog={async () => CATALOG}
      />,
    );

    expect(await screen.findByLabelText(/OpenRouter model/i)).toHaveValue(
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
    const select = screen.getByLabelText(/^Ollama model$/i);
    expect(select.tagName).toBe("SELECT");
    expect(
      within(select).getByRole("option", { name: "mistral" }),
    ).toBeInTheDocument();
  });

  it("shows a safe error when the catalog fails", async () => {
    render(
      <SettingsPanel
        apiBaseUrl="http://127.0.0.1:8000"
        loadCatalog={async () => {
          throw new Error("boom");
        }}
      />,
    );

    expect(
      await screen.findByText(/Settings catalog unavailable/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/boom|Traceback/i)).not.toBeInTheDocument();
  });
});
