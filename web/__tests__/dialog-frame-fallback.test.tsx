import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("motion/react", () => {
  return {
    useReducedMotion: () => true,
    AnimatePresence: ({
      children,
    }: {
      children?: ReactNode;
      onExitComplete?: () => void;
    }) => <>{children}</>,
    motion: {
      button: ({
        children,
        ...props
      }: React.ButtonHTMLAttributes<HTMLButtonElement> & {
        children?: ReactNode;
      }) => <button {...props}>{children}</button>,
      div: ({
        children,
        ...props
      }: React.HTMLAttributes<HTMLDivElement> & { children?: ReactNode }) => (
        <div {...props}>{children}</div>
      ),
    },
  };
});

import { DialogFrame, RESTORE_FALLBACK_MS } from "@/components/ui/DialogFrame";

describe("DialogFrame restore fallback timer", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("restores via the fallback timer using the panel captured at arm time", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({
      advanceTimers: vi.advanceTimersByTime.bind(vi),
    });

    function Harness() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>
            Open
          </button>
          <DialogFrame
            open={open}
            titleId="fallback-title"
            onDismiss={() => setOpen(false)}
          >
            <h2 id="fallback-title">Panel</h2>
            <button type="button" onClick={() => setOpen(false)}>
              Close
            </button>
          </DialogFrame>
        </>
      );
    }

    render(<Harness />);
    const openButton = screen.getByRole("button", { name: /^open$/i });
    await user.click(openButton);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^close$/i }));

    // AnimatePresence mock never fires onExitComplete — only the timer restores.
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(RESTORE_FALLBACK_MS);
    });

    await waitFor(() => {
      expect(document.activeElement).toBe(openButton);
    });
  });
});
