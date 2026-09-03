"use client";

type GlobalErrorProps = {
  error: Error & { digest?: string };
  reset: () => void;
};

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
          fontFamily:
            'system-ui, -apple-system, "Segoe UI", sans-serif',
          color: "light-dark(#222222, #f1f1ef)",
          background: "light-dark(#f4f4f2, #151515)",
          colorScheme: "light dark",
        }}
      >
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
              color: "light-dark(#666662, #adada7)",
              fontSize: "0.95rem",
              lineHeight: 1.6,
            }}
          >
            A safe global error boundary without exposing internal details.
          </p>
          <button
            type="button"
            onClick={() => reset()}
            style={{
              minHeight: 44,
              padding: "0 14px",
              border: "1px solid light-dark(#d4d4cf, #41413e)",
              borderRadius: 7,
              color: "inherit",
              background: "light-dark(#ffffff, #202020)",
              cursor: "pointer",
              font: "inherit",
            }}
          >
            Try again
          </button>
        </div>
      </body>
    </html>
  );
}
