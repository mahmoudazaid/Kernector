import { z } from "zod";

const publicEnvSchema = z.object({
  NEXT_PUBLIC_APP_NAME: z.string().min(1).default("Kernector"),
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
    if (FORBIDDEN_PUBLIC_PATTERN.test(suffix) || FORBIDDEN_PUBLIC_PATTERN.test(key)) {
      throw new EnvValidationError(
        `Forbidden secret-shaped public environment key "${key}" must not be exposed through public env.`,
      );
    }
  }

  const parsed = publicEnvSchema.safeParse({
    NEXT_PUBLIC_APP_NAME: source.NEXT_PUBLIC_APP_NAME ?? "Kernector",
  });

  if (!parsed.success) {
    throw new EnvValidationError(parsed.error.message);
  }

  return parsed.data;
}
