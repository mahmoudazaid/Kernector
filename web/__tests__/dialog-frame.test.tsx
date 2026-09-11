import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRef, useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { DialogFrame, RESTORE_FALLBACK_MS } from "@/components/ui/DialogFrame";

function Harness() {
  const [open, setOpen] = useState(true);
  return (
    <DialogFrame
      open={open}
      titleId="dialog-title"
      onDismiss={() => setOpen(false)}
    >
      <h2 id="dialog-title">Confirm delete</h2>
    </DialogFrame>
  );
}

function RestoreFocusHarness() {
  const [open, setOpen] = useState(false);
  const restoreRef = useRef<HTMLButtonElement>(null);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Open
      </button>
      <button type="button" ref={restoreRef}>
        Restore target
      </button>
      <DialogFrame
        open={open}
        titleId="restore-title"
        restoreFocusRef={restoreRef}
        onDismiss={() => setOpen(false)}
      >
        <h2 id="restore-title">Panel</h2>
        <button type="button" onClick={() => setOpen(false)}>
          Close
        </button>
      </DialogFrame>
    </>
  );
}

describe("DialogFrame", () => {
  it("shows a dialog and dismisses on backdrop click", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    expect(
      screen.getByRole("dialog", { name: /confirm delete/i }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /dismiss dialog/i }));

    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  it("restores focus to restoreFocusRef instead of the opener", async () => {
    const user = userEvent.setup();
    render(<RestoreFocusHarness />);

    await user.click(screen.getByRole("button", { name: /^open$/i }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^close$/i }));

    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: /restore target/i }),
    );
  });

  it("skips a detached restore target and uses the opener", async () => {
    const user = userEvent.setup();
    function SkipDetachedHarness() {
      const [open, setOpen] = useState(false);
      const [gone, setGone] = useState(false);
      // Hold a live Element reference that survives React unmounting the node.
      const restoreRef = useRef<HTMLElement | null>(null);
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>
            Open
          </button>
          {!gone ? (
            <button type="button" id="restore-target" onClick={() => undefined}>
              Detached target
            </button>
          ) : null}
          <DialogFrame
            open={open}
            titleId="skip-title"
            restoreFocusRef={restoreRef}
            onDismiss={() => {
              const node = document.getElementById("restore-target");
              if (node) {
                restoreRef.current = node;
              }
              setGone(true);
              setOpen(false);
            }}
          >
            <h2 id="skip-title">Panel</h2>
            <button
              type="button"
              onClick={() => {
                const node = document.getElementById("restore-target");
                if (node) {
                  restoreRef.current = node;
                }
                setGone(true);
                setOpen(false);
              }}
            >
              Close
            </button>
          </DialogFrame>
        </>
      );
    }
    render(<SkipDetachedHarness />);

    await user.click(screen.getByRole("button", { name: /^open$/i }));
    await user.click(screen.getByRole("button", { name: /^close$/i }));

    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
    expect(document.getElementById("restore-target")).toBeNull();
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: /^open$/i }),
    );
  });

  it("does not treat the backdrop as the restore opener", async () => {
    const user = userEvent.setup();
    function BackdropHarness() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>
            Open
          </button>
          <DialogFrame
            open={open}
            titleId="backdrop-title"
            onDismiss={() => setOpen(false)}
          >
            <h2 id="backdrop-title">Panel</h2>
          </DialogFrame>
        </>
      );
    }
    render(<BackdropHarness />);

    const openButton = screen.getByRole("button", { name: /^open$/i });
    await user.click(openButton);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /dismiss dialog/i }));

    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
    expect(document.activeElement).toBe(openButton);
  });

  it("does not steal focus from an element outside the dialog on exit", async () => {
    const user = userEvent.setup();
    function ExternalFocusHarness() {
      const [open, setOpen] = useState(false);
      const alertRef = useRef<HTMLDivElement>(null);
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>
            Open
          </button>
          <div
            ref={alertRef}
            role="alert"
            tabIndex={-1}
            data-testid="fresh-alert"
          >
            The request failed
          </div>
          <DialogFrame
            open={open}
            titleId="alert-title"
            onDismiss={() => {
              setOpen(false);
              queueMicrotask(() => alertRef.current?.focus());
            }}
          >
            <h2 id="alert-title">Panel</h2>
            <button type="button" onClick={() => setOpen(false)}>
              Close
            </button>
          </DialogFrame>
        </>
      );
    }
    render(<ExternalFocusHarness />);

    await user.click(screen.getByRole("button", { name: /^open$/i }));
    await user.click(screen.getByRole("button", { name: /dismiss dialog/i }));

    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
    await waitFor(() => {
      expect(document.activeElement).toBe(screen.getByTestId("fresh-alert"));
    });
  });

  it("clears the fallback timer when exit completes", async () => {
    const user = userEvent.setup();
    const fallbackIds = new Set<number>();
    const realSetTimeout = window.setTimeout.bind(window);
    const setSpy = vi.spyOn(window, "setTimeout").mockImplementation(((
      handler: TimerHandler,
      delay?: number,
      ...args: unknown[]
    ) => {
      const id = realSetTimeout(handler, delay, ...(args as []));
      if (delay === RESTORE_FALLBACK_MS) {
        fallbackIds.add(id as unknown as number);
      }
      return id;
    }) as typeof setTimeout);
    const clearSpy = vi.spyOn(window, "clearTimeout");
    try {
      function Harness() {
        const [open, setOpen] = useState(false);
        return (
          <>
            <button type="button" onClick={() => setOpen(true)}>
              Open
            </button>
            <DialogFrame
              open={open}
              titleId="clear-title"
              onDismiss={() => setOpen(false)}
            >
              <h2 id="clear-title">Panel</h2>
            </DialogFrame>
          </>
        );
      }
      render(<Harness />);
      await user.click(screen.getByRole("button", { name: /^open$/i }));
      clearSpy.mockClear();
      fallbackIds.clear();
      await user.click(screen.getByRole("button", { name: /dismiss dialog/i }));
      await waitFor(() => {
        expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      });
      expect(fallbackIds.size).toBeGreaterThan(0);
      for (const id of fallbackIds) {
        expect(clearSpy).toHaveBeenCalledWith(id);
      }
    } finally {
      setSpy.mockRestore();
      clearSpy.mockRestore();
    }
  });

  it("restores focus when the frame unmounts before exit completes", async () => {
    const user = userEvent.setup();
    function UnmountHarness() {
      const [showFrame, setShowFrame] = useState(true);
      const [open, setOpen] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>
            Open
          </button>
          {showFrame ? (
            <DialogFrame
              open={open}
              titleId="unmount-title"
              onDismiss={() => {
                setOpen(false);
                setShowFrame(false);
              }}
            >
              <h2 id="unmount-title">Panel</h2>
            </DialogFrame>
          ) : null}
        </>
      );
    }
    render(<UnmountHarness />);

    const openButton = screen.getByRole("button", { name: /^open$/i });
    await user.click(openButton);
    await user.click(screen.getByRole("button", { name: /dismiss dialog/i }));

    // No waitFor: the restore must not depend on RESTORE_FALLBACK_MS.
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(document.activeElement).toBe(openButton);
  });
});
