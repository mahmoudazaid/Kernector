"use client";

type GlobalErrorProps = {
  error: Error & { digest?: string };
  reset: () => void;
};

type GlobalErrorFallbackProps = {
  onRetry: () => void;
};

/**
 * Resilient root fallback UI. Kept free of AppShell, Providers, env parsing,
 * and remote APIs so it still works when the root layout fails.
 */
export function GlobalErrorFallback({ onRetry }: GlobalErrorFallbackProps) {
  return (
    <div
      role="alert"
      style={{
        width: "min(480px, 100%)",
        textAlign: "center",
      }}
    >
      <h1
        style={{
          margin: "0 0 8px",
          fontSize: "1.25rem",
          fontWeight: 500,
        }}
      >
        Something went wrong
      </h1>
      <p
        style={{
          margin: "0 0 18px",
          color: "light-dark(#5a6a76, #9aadb8)",
          fontSize: "0.95rem",
          lineHeight: 1.6,
        }}
      >
        A safe global error boundary without exposing internal details.
      </p>
      <button
        type="button"
        onClick={onRetry}
        style={{
          minHeight: 44,
          padding: "0 14px",
          border: "1px solid light-dark(#c9d3db, #33424d)",
          borderRadius: 6,
          color: "inherit",
          background: "light-dark(#ffffff, #1a2128)",
          cursor: "pointer",
          font: "inherit",
        }}
      >
        Try again
      </button>
    </div>
  );
}

/**
 * Root-level error boundary. Replaces the root layout when active, so this
 * module must stay free of AppShell, Providers, env parsing, and remote APIs.
 */
export default function GlobalError({ reset }: GlobalErrorProps) {
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "grid",
          placeItems: "center",
          padding: "24px",
          fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif',
          color: "light-dark(#1a232b, #e8eef2)",
          background: "light-dark(#f1f4f6, #0f1418)",
          colorScheme: "light dark",
        }}
      >
        <GlobalErrorFallback onRetry={() => reset()} />
      </body>
    </html>
  );
}
