import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRef, useState } from "react";
import { describe, expect, it } from "vitest";
import { DialogFrame } from "@/components/ui/DialogFrame";

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
});
