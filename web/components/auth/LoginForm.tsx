"use client";

import { useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/Button";
import { KernectorMark } from "@/components/shell/KernectorMark";
import { ApiError } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth/use-auth";

function safeNextPath(raw: string | null): string {
  if (!raw || !raw.startsWith("/") || raw.startsWith("//")) {
    return "/";
  }
  if (raw === "/login" || raw.startsWith("/login?")) {
    return "/";
  }
  return raw;
}

export function LoginForm() {
  const { signIn } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      await signIn(username, password);
      router.replace(safeNextPath(searchParams.get("next")));
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setError("Invalid username or password");
      } else if (err instanceof ApiError && err.status === 403) {
        setError("Sign-in is not allowed from this origin.");
      } else {
        setError("Sign-in failed. Please try again.");
      }
    } finally {
      setPending(false);
      setPassword("");
    }
  }

  return (
    <div className="kern-login">
      <div className="kern-login-brand" aria-hidden="true">
        <KernectorMark className="kern-login-mark" />
      </div>
      <header className="kern-page-heading">
        <h1>Sign in</h1>
        <p>Local account. Create users with the CLI.</p>
      </header>

      <form className="kern-login-form" onSubmit={onSubmit}>
        <fieldset className="kern-settings-fieldset">
          <legend>Credentials</legend>
          <div className="kern-settings-stack">
            <div className="kern-settings-field">
              <label htmlFor="login-username">Username</label>
              <input
                id="login-username"
                className="kern-settings-input"
                name="username"
                autoComplete="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                autoFocus
              />
            </div>
            <div className="kern-settings-field">
              <label htmlFor="login-password">Password</label>
              <input
                id="login-password"
                className="kern-settings-input"
                name="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                aria-invalid={error ? true : undefined}
              />
            </div>
          </div>
        </fieldset>

        {error ? (
          <p className="kern-login-error" role="alert">
            {error}
          </p>
        ) : null}

        <Button type="submit" disabled={pending}>
          {pending ? "Signing in…" : "Sign in"}
        </Button>
      </form>
    </div>
  );
}
