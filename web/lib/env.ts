import { z } from "zod";

const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";

const httpUrl = z
  .string()
  .url()
  .refine(
    (value) => {
      try {
        const protocol = new URL(value).protocol;
        return protocol === "http:" || protocol === "https:";
      } catch {
        return false;
      }
    },
    { message: "API base URL must be an absolute http(s) URL" },
  )
  .transform((value) => value.replace(/\/+$/, ""));

const publicEnvSchema = z.object({
  NEXT_PUBLIC_APP_NAME: z.string().min(1).default("Kernector"),
  NEXT_PUBLIC_API_BASE_URL: httpUrl.default(DEFAULT_API_BASE_URL),
});

const FORBIDDEN_PUBLIC_PATTERN =
  /(SECRET|TOKEN|PASSWORD|API_KEY|PRIVATE|DATABASE_URL|OPENAI|OPENROUTER|CHROMA)/i;

export class EnvValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "EnvValidationError";
  }
}

export type PublicEnv = z.infer<typeof publicEnvSchema>;

export function loadPublicEnv(
  source: Record<string, string | undefined> = process.env as Record<
    string,
    string | undefined
  >,
): PublicEnv {
  for (const key of Object.keys(source)) {
    if (!key.startsWith("NEXT_PUBLIC_") || source[key] === undefined) {
      continue;
    }
    const suffix = key.slice("NEXT_PUBLIC_".length);
    if (
      FORBIDDEN_PUBLIC_PATTERN.test(suffix) ||
      FORBIDDEN_PUBLIC_PATTERN.test(key)
    ) {
      throw new EnvValidationError(
        `Forbidden secret-shaped public environment key "${key}" must not be exposed through public env.`,
      );
    }
  }

  const parsed = publicEnvSchema.safeParse({
    NEXT_PUBLIC_APP_NAME: source.NEXT_PUBLIC_APP_NAME ?? "Kernector",
    NEXT_PUBLIC_API_BASE_URL:
      source.NEXT_PUBLIC_API_BASE_URL ?? DEFAULT_API_BASE_URL,
  });

  if (!parsed.success) {
    throw new EnvValidationError(parsed.error.message);
  }

  return parsed.data;
}
