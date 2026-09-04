import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { BackendStatus } from "@/components/shell/BackendStatus";
import type { HealthAvailability } from "@/lib/api/health";

describe("BackendStatus", () => {
  it("announces a pending state while probing", () => {
    const probe = () =>
      new Promise<HealthAvailability>(() => {
        /* never resolves during this assertion */
      });

    render(<BackendStatus apiBaseUrl="http://127.0.0.1:8000" probe={probe} />);

    expect(screen.getByText(/checking backend/i)).toBeInTheDocument();
  });

  it("shows Available when health succeeds", async () => {
    render(
      <BackendStatus
        apiBaseUrl="http://127.0.0.1:8000"
        probe={async () => ({ available: true })}
      />,
    );

    expect(await screen.findByText(/^Available$/i)).toBeInTheDocument();
  });

  it("shows Unavailable with safe copy and no internals", async () => {
    render(
      <BackendStatus
        apiBaseUrl="http://127.0.0.1:8000"
        probe={async () => ({
          available: false,
          message: "The service is temporarily unavailable.",
        })}
      />,
    );

    expect(await screen.findByText(/^Unavailable$/i)).toBeInTheDocument();
    expect(screen.getByText(/temporarily unavailable/i)).toBeInTheDocument();

    const region = screen.getByRole("status");
    expect(region.textContent).not.toMatch(/Traceback|stack/i);
    expect(region.textContent).not.toContain("https://kernector.dev/problems/");
    expect(region.textContent).not.toMatch(/\{.*"type":/);
  });

  it("does not render raw problem JSON from a toxic message", async () => {
    const toxic = JSON.stringify({
      type: "https://kernector.dev/problems/error",
      stack: "Traceback (most recent call last)",
    });

    render(
      <BackendStatus
        apiBaseUrl="http://127.0.0.1:8000"
        probe={async () => ({ available: false, message: toxic })}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText(/^Unavailable$/i)).toBeInTheDocument();
    });

    const region = screen.getByRole("status");
    // Label is always safe; detail uses a sanitized fallback when message looks like JSON.
    expect(region.textContent).not.toContain("Traceback");
  });
});
