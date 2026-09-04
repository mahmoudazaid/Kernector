import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/errors";
import { getOllamaStatus } from "@/lib/api/ollama";
import { getRuntimeSettings } from "@/lib/api/settings";

const CATALOG = {
  providers: ["openrouter", "ollama"],
  default_provider: "openrouter",
  openrouter: {
    models: ["openai/gpt-4o-mini"],
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
  ],
};

describe("getRuntimeSettings", () => {
  it("returns the runtime settings catalog", async () => {
    const request = vi.fn().mockResolvedValue(CATALOG);

    const result = await getRuntimeSettings({
      baseUrl: "http://127.0.0.1:8000",
      request,
    });

    expect(result).toEqual(CATALOG);
    expect(request).toHaveBeenCalledWith(
      expect.objectContaining({
        baseUrl: "http://127.0.0.1:8000",
        path: "/api/v1/settings",
        method: "GET",
      }),
    );
  });

  it("propagates ApiError from the transport", async () => {
    await expect(
      getRuntimeSettings({
        baseUrl: "http://127.0.0.1:8000",
        request: async () => {
          throw new ApiError({
            status: 500,
            title: "Server error",
            detail: "An unexpected error occurred.",
            code: "internal_error",
          });
        },
      }),
    ).rejects.toBeInstanceOf(ApiError);
  });
});

describe("getOllamaStatus", () => {
  it("returns probe status for the configured Ollama URL", async () => {
    const request = vi.fn().mockResolvedValue({
      reachable: true,
      models: ["llama3.2"],
    });

    const result = await getOllamaStatus({
      baseUrl: "http://127.0.0.1:8000",
      request,
    });

    expect(result).toEqual({ reachable: true, models: ["llama3.2"] });
    expect(request).toHaveBeenCalledWith(
      expect.objectContaining({
        path: "/api/v1/ollama/status",
        method: "GET",
      }),
    );
  });

  it("propagates conflict ApiError when Ollama is unconfigured", async () => {
    await expect(
      getOllamaStatus({
        baseUrl: "http://127.0.0.1:8000",
        request: async () => {
          throw new ApiError({
            status: 409,
            title: "HTTP error",
            detail: "The request could not be completed.",
            code: "http_409",
          });
        },
      }),
    ).rejects.toMatchObject({ status: 409, code: "http_409" });
  });
});
