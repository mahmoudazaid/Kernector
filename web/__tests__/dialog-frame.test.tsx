import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
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

describe("DialogFrame", () => {
  it("shows a dialog and dismisses on backdrop click", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    expect(
      screen.getByRole("dialog", { name: /confirm delete/i }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /dismiss dialog/i }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
