"use client";

import {
  useCallback,
  useEffect,
  useRef,
  type ReactNode,
  type RefObject,
} from "react";

const FOCUSABLE_SELECTOR = [
  "button:not([disabled])",
  "[href]",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(", ");

/** Fallback when the sheet unmounts before focus can restore. */
export const SHEET_RESTORE_FALLBACK_MS = 600;

export type SheetProps = {
  open: boolean;
  titleId: string;
  descriptionId?: string;
  panelClassName?: string;
  initialFocusRef?: RefObject<HTMLElement | null>;
  /** When set, prefer this target on close if it is still focusable. */
  restoreFocusRef?: RefObject<HTMLElement | null>;
  dismissDisabled?: boolean;
  onDismiss: () => void;
  children?: ReactNode;
};

function focusableNodes(root: HTMLElement | null): HTMLElement[] {
  if (!root) {
    return [];
  }
  return Array.from(
    root.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
  ).filter((node) => !node.hasAttribute("disabled") && node.tabIndex !== -1);
}

function isRestorable(
  node: HTMLElement | null | undefined,
): node is HTMLElement {
  return Boolean(
    node &&
      node.isConnected &&
      !node.hasAttribute("disabled") &&
      node.getAttribute("aria-disabled") !== "true",
  );
}

function isSheetChrome(node: Element): boolean {
  return Boolean(node.closest(".kern-sheet-root, .kern-sheet-backdrop"));
}

function restoreFocus(
  ...candidates: Array<HTMLElement | null | undefined>
): void {
  for (const candidate of candidates) {
    if (isRestorable(candidate)) {
      candidate.focus();
      return;
    }
  }
}

function focusAlreadyMovedOn(
  panel: HTMLElement | null,
  backdrop: HTMLElement | null,
): boolean {
  const active = document.activeElement;
  if (!active || active === document.body) {
    return false;
  }
  if (panel?.closest(".kern-sheet-root")?.contains(active)) {
    return false;
  }
  if (backdrop && active === backdrop) {
    return false;
  }
  return true;
}

/**
 * Right-side sheet dialog (shadcn Sheet pattern) with focus trap, Escape /
 * backdrop dismiss, and focus restoration. Uses CSS transitions only — no
 * Motion dependency for this surface.
 */
export function Sheet({
  open,
  titleId,
  descriptionId,
  panelClassName,
  initialFocusRef,
  restoreFocusRef,
  dismissDisabled = false,
  onDismiss,
  children,
}: SheetProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const panelNodeRef = useRef<HTMLDivElement | null>(null);
  const backdropRef = useRef<HTMLButtonElement | null>(null);
  const onDismissRef = useRef(onDismiss);
  onDismissRef.current = onDismiss;
  const dismissDisabledRef = useRef(dismissDisabled);
  dismissDisabledRef.current = dismissDisabled;
  const initialFocusRefStored = useRef(initialFocusRef);
  initialFocusRefStored.current = initialFocusRef;
  const restoreFocusRefStored = useRef(restoreFocusRef);
  restoreFocusRefStored.current = restoreFocusRef;
  const openerRef = useRef<HTMLElement | null>(null);
  const pendingRestoreRef = useRef<Array<
    HTMLElement | null | undefined
  > | null>(null);
  const restoreFallbackTimerRef = useRef<number | null>(null);

  const setPanelNode = useCallback((node: HTMLDivElement | null) => {
    panelRef.current = node;
    if (node) {
      panelNodeRef.current = node;
    }
  }, []);

  const clearRestoreFallbackTimer = useCallback(() => {
    if (restoreFallbackTimerRef.current != null) {
      window.clearTimeout(restoreFallbackTimerRef.current);
      restoreFallbackTimerRef.current = null;
    }
  }, []);

  const consumePendingRestore = useCallback(
    (panel: HTMLElement | null) => {
      const pending = pendingRestoreRef.current;
      if (!pending) {
        return;
      }
      pendingRestoreRef.current = null;
      panelNodeRef.current = null;
      clearRestoreFallbackTimer();
      if (!focusAlreadyMovedOn(panel, backdropRef.current)) {
        restoreFocus(...pending);
      }
    },
    [clearRestoreFallbackTimer],
  );

  useEffect(() => {
    function rememberOpener(event: Event) {
      const target = event.target;
      if (!(target instanceof Element)) {
        return;
      }
      if (panelRef.current?.contains(target) || isSheetChrome(target)) {
        return;
      }
      const candidate =
        target instanceof HTMLElement && target.matches(FOCUSABLE_SELECTOR)
          ? target
          : target.closest<HTMLElement>(FOCUSABLE_SELECTOR);
      if (isRestorable(candidate)) {
        openerRef.current = candidate;
      }
    }
    document.addEventListener("pointerdown", rememberOpener, true);
    document.addEventListener("keydown", rememberOpener, true);
    return () => {
      document.removeEventListener("pointerdown", rememberOpener, true);
      document.removeEventListener("keydown", rememberOpener, true);
    };
  }, []);

  useEffect(() => {
    if (!open) {
      return;
    }
    pendingRestoreRef.current = null;
    clearRestoreFallbackTimer();
    const previous =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    const target =
      initialFocusRefStored.current?.current ??
      focusableNodes(panelRef.current)[0] ??
      panelRef.current;
    target?.focus();

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        if (!dismissDisabledRef.current) {
          onDismissRef.current();
        }
        return;
      }
      if (event.key !== "Tab") {
        return;
      }
      const nodes = focusableNodes(panelRef.current);
      if (nodes.length === 0) {
        event.preventDefault();
        return;
      }
      const first = nodes[0];
      const last = nodes[nodes.length - 1];
      const active = document.activeElement;
      if (event.shiftKey) {
        if (active === first || !panelRef.current?.contains(active)) {
          event.preventDefault();
          last.focus();
        }
        return;
      }
      if (active === last || !panelRef.current?.contains(active)) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      pendingRestoreRef.current = [
        restoreFocusRefStored.current?.current,
        openerRef.current,
        previous,
      ];
      const panelAtArm = panelNodeRef.current ?? panelRef.current;
      restoreFallbackTimerRef.current = window.setTimeout(() => {
        restoreFallbackTimerRef.current = null;
        consumePendingRestore(panelAtArm);
      }, SHEET_RESTORE_FALLBACK_MS);
    };
  }, [open, clearRestoreFallbackTimer, consumePendingRestore]);

  useEffect(() => {
    return () => {
      consumePendingRestore(panelNodeRef.current);
    };
  }, [consumePendingRestore]);

  useEffect(() => {
    if (!open) {
      consumePendingRestore(panelNodeRef.current);
    }
  }, [open, consumePendingRestore]);

  if (!open) {
    return null;
  }

  return (
    <>
      <button
        type="button"
        ref={backdropRef}
        className="kern-sheet-backdrop"
        aria-label="Dismiss sheet"
        disabled={dismissDisabled}
        onClick={() => {
          if (!dismissDisabled) {
            onDismiss();
          }
        }}
      />
      <div className="kern-sheet-root" data-state="open">
        <div
          ref={setPanelNode}
          className={["kern-sheet", panelClassName].filter(Boolean).join(" ")}
          role="dialog"
          aria-modal="true"
          aria-labelledby={titleId}
          aria-describedby={descriptionId}
          tabIndex={-1}
        >
          {children}
        </div>
      </div>
    </>
  );
}
