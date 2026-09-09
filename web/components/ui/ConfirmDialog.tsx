"use client";

import { useId, useRef } from "react";
import { Button } from "@/components/ui/Button";
import { DialogFrame } from "@/components/ui/DialogFrame";

export type ConfirmDialogProps = {
  open: boolean;
  title: string;
  description: string;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: "default" | "danger";
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
};

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  tone = "default",
  busy = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const titleId = useId();
  const descriptionId = useId();
  const cancelRef = useRef<HTMLButtonElement>(null);

  return (
    <DialogFrame
      open={open}
      titleId={titleId}
      descriptionId={descriptionId}
      initialFocusRef={cancelRef}
      onDismiss={onCancel}
    >
      <h2 id={titleId} className="kern-dialog-title">
        {title}
      </h2>
      <p id={descriptionId} className="kern-dialog-body">
        {description}
      </p>
      <div className="kern-dialog-actions">
        <Button ref={cancelRef} variant="secondary" onClick={onCancel}>
          {cancelLabel}
        </Button>
        <Button
          variant={tone === "danger" ? "danger" : "default"}
          disabled={busy}
          onClick={onConfirm}
        >
          {confirmLabel}
        </Button>
      </div>
    </DialogFrame>
  );
}
