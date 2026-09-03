import { describe, expect, it } from "vitest";
import { EnvValidationError, loadPublicEnv } from "@/lib/env";

describe("public env safety", () => {
  it("accepts documented public environment variables", () => {
    const env = loadPublicEnv({
      NEXT_PUBLIC_APP_NAME: "Kernector",
    });

    expect(env.NEXT_PUBLIC_APP_NAME).toBe("Kernector");
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
    expect(env).not.toHaveProperty("OPENROUTER_API_KEY");
    expect(env).not.toHaveProperty("DATABASE_URL");
  });
});
