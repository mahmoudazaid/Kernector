import { describe, expect, it } from "vitest";
import { EnvValidationError, loadPublicEnv } from "@/lib/env";

describe("public env safety", () => {
  it("accepts documented public environment variables", () => {
    const env = loadPublicEnv({
      NEXT_PUBLIC_APP_NAME: "Kernector",
    });

    expect(env.NEXT_PUBLIC_APP_NAME).toBe("Kernector");
    expect(env.NEXT_PUBLIC_API_BASE_URL).toBe("http://127.0.0.1:8000");
  });

  it("defaults API base URL when unset", () => {
    const env = loadPublicEnv({
      NEXT_PUBLIC_APP_NAME: "Kernector",
    });

    expect(env.NEXT_PUBLIC_API_BASE_URL).toBe("http://127.0.0.1:8000");
  });

  it("accepts an absolute http API base URL", () => {
    const env = loadPublicEnv({
      NEXT_PUBLIC_APP_NAME: "Kernector",
      NEXT_PUBLIC_API_BASE_URL: "http://127.0.0.1:8000",
    });

    expect(env.NEXT_PUBLIC_API_BASE_URL).toBe("http://127.0.0.1:8000");
  });

  it("accepts an absolute https API base URL and strips a trailing slash", () => {
    const env = loadPublicEnv({
      NEXT_PUBLIC_APP_NAME: "Kernector",
      NEXT_PUBLIC_API_BASE_URL: "https://api.example.com/",
    });

    expect(env.NEXT_PUBLIC_API_BASE_URL).toBe("https://api.example.com");
  });

  it("rejects relative, non-http, and invalid API base URLs", () => {
    expect(() =>
      loadPublicEnv({
        NEXT_PUBLIC_APP_NAME: "Kernector",
        NEXT_PUBLIC_API_BASE_URL: "/api",
      }),
    ).toThrow(EnvValidationError);

    expect(() =>
      loadPublicEnv({
        NEXT_PUBLIC_APP_NAME: "Kernector",
        NEXT_PUBLIC_API_BASE_URL: "ftp://example.com",
      }),
    ).toThrow(EnvValidationError);

    expect(() =>
      loadPublicEnv({
        NEXT_PUBLIC_APP_NAME: "Kernector",
        NEXT_PUBLIC_API_BASE_URL: "not-a-url",
      }),
    ).toThrow(EnvValidationError);
  });

  it("rejects secret-shaped NEXT_PUBLIC keys", () => {
    expect(() =>
      loadPublicEnv({
        NEXT_PUBLIC_APP_NAME: "Kernector",
        NEXT_PUBLIC_SECRET_TOKEN: "leak",
      }),
    ).toThrow(EnvValidationError);

    expect(() =>
      loadPublicEnv({
        NEXT_PUBLIC_APP_NAME: "Kernector",
        NEXT_PUBLIC_OPENAI_API_KEY: "sk-secret",
      }),
    ).toThrow(/secret|forbidden|public/i);
  });

  it("ignores non-public secrets already present in the process environment", () => {
    const env = loadPublicEnv({
      NEXT_PUBLIC_APP_NAME: "Kernector",
      OPENROUTER_API_KEY: "sk-server-only",
      DATABASE_URL: "postgres://example",
    });

    expect(env.NEXT_PUBLIC_APP_NAME).toBe("Kernector");
    expect(env.NEXT_PUBLIC_API_BASE_URL).toBe("http://127.0.0.1:8000");
    expect(env).not.toHaveProperty("OPENROUTER_API_KEY");
    expect(env).not.toHaveProperty("DATABASE_URL");
  });
});
