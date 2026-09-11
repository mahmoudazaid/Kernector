import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("motion/react", () => {
  function hasContent(node: ReactNode): boolean {
    if (node == null || node === false || node === true) {
      return false;
    }
    if (Array.isArray(node)) {
      return node.some(hasContent);
    }
    return true;
  }

  function HeldAnimatePresence({
    children,
    onExitComplete,
  }: {
    children?: ReactNode;
    onExitComplete?: () => void;
  }) {
    const [shown, setShown] = useState(children);
    const onExit = useRef(onExitComplete);
    onExit.current = onExitComplete;
    const exitTimer = useRef<number | null>(null);
    useEffect(() => {
      if (hasContent(children)) {
        if (exitTimer.current != null) {
          window.clearTimeout(exitTimer.current);
          exitTimer.current = null;
        }
        setShown(children);
        return;
      }
      // Keep the exiting panel mounted past RESTORE_FALLBACK_MS so the timer
      // races while focus is still inside the panel.
      exitTimer.current = window.setTimeout(() => {
        exitTimer.current = null;
        setShown(null);
        onExit.current?.();
      }, 10_000);
      return () => {
        if (exitTimer.current != null) {
          window.clearTimeout(exitTimer.current);
        }
      };
    }, [children]);
    return <>{shown}</>;
  }

  return {
    useReducedMotion: () => true,
    AnimatePresence: HeldAnimatePresence,
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

  it("restores via the fallback timer while the exiting panel still holds focus", async () => {
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
    const closeButton = screen.getByRole("button", { name: /^close$/i });
    closeButton.focus();
    expect(document.activeElement).toBe(closeButton);
    await user.click(closeButton);

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: /^close$/i }),
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(RESTORE_FALLBACK_MS);
    });

    await waitFor(() => {
      expect(document.activeElement).toBe(openButton);
    });
  });
});
