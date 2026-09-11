"use client";

import { useEffect, useRef, type ReactNode, type RefObject } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";

const FOCUSABLE_SELECTOR = [
  "button:not([disabled])",
  "[href]",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(", ");

const BACKDROP_TRANSITION = { duration: 0.2, ease: "easeOut" as const };

const PANEL_SPRING = {
  type: "spring" as const,
  duration: 0.5,
  bounce: 0.2,
};

const FADE_ONLY = { duration: 0.2, ease: "easeOut" as const };

/** Fallback when AnimatePresence exit is interrupted (e.g. frame unmount). */
export const RESTORE_FALLBACK_MS = 600;

export type DialogFrameProps = {
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

function isDialogChrome(node: Element): boolean {
  return Boolean(node.closest(".kern-dialog-root, .kern-dialog-backdrop"));
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

function focusAlreadyMovedOn(panel: HTMLElement | null): boolean {
  const active = document.activeElement;
  if (!active || active === document.body) {
    return false;
  }
  // Focus already moved on (a fresh alert, the user's own Tab): leave it.
  if (panel?.contains(active)) {
    return false;
  }
  if (isDialogChrome(active)) {
    return false;
  }
  return true;
}

export function DialogFrame({
  open,
  titleId,
  descriptionId,
  panelClassName,
  initialFocusRef,
  restoreFocusRef,
  dismissDisabled = false,
  onDismiss,
  children,
}: DialogFrameProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  /** Survives cleanup timing: last non-null panel node while the dialog was open. */
  const panelNodeRef = useRef<HTMLDivElement | null>(null);
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
  const exitingPanelRef = useRef<HTMLElement | null>(null);
  const restoreFallbackTimerRef = useRef<number | null>(null);
  const reduceMotion = useReducedMotion();

  useEffect(() => {
    function rememberOpener(event: Event) {
      const target = event.target;
      if (!(target instanceof Element)) {
        return;
      }
      // Dialog chrome is never the opener: the backdrop is a <button> that
      // outlives the close by one exit animation, so it would beat the opener.
      if (panelRef.current?.contains(target) || isDialogChrome(target)) {
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

  // Clear a live fallback timer on unmount; restore immediately if still armed.
  useEffect(() => {
    return () => {
      if (restoreFallbackTimerRef.current != null) {
        window.clearTimeout(restoreFallbackTimerRef.current);
        restoreFallbackTimerRef.current = null;
      }
      const pending = pendingRestoreRef.current;
      if (!pending) {
        return;
      }
      pendingRestoreRef.current = null;
      const panel = exitingPanelRef.current;
      exitingPanelRef.current = null;
      if (!focusAlreadyMovedOn(panel)) {
        restoreFocus(...pending);
      }
    };
  }, []);

  useEffect(() => {
    if (!open) {
      return;
    }
    // Cancel a restore still waiting on a previous exit animation.
    pendingRestoreRef.current = null;
    exitingPanelRef.current = null;
    if (restoreFallbackTimerRef.current != null) {
      window.clearTimeout(restoreFallbackTimerRef.current);
      restoreFallbackTimerRef.current = null;
    }
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
      // Defer until AnimatePresence exit completes so aria-modal is gone.
      pendingRestoreRef.current = [
        restoreFocusRefStored.current?.current,
        openerRef.current,
        previous,
      ];
      // Capture now: the timer may fire while the panel is still focused mid-exit.
      const exitingPanel = panelNodeRef.current;
      exitingPanelRef.current = exitingPanel;
      // Interrupted exits (frame unmount mid-animation) skip onExitComplete.
      restoreFallbackTimerRef.current = window.setTimeout(() => {
        restoreFallbackTimerRef.current = null;
        const pending = pendingRestoreRef.current;
        if (!pending) {
          return;
        }
        pendingRestoreRef.current = null;
        exitingPanelRef.current = null;
        if (!focusAlreadyMovedOn(exitingPanel)) {
          restoreFocus(...pending);
        }
      }, RESTORE_FALLBACK_MS);
    };
  }, [open]);

  return (
    <AnimatePresence
      onExitComplete={() => {
        const pending = pendingRestoreRef.current;
        if (!pending) {
          return;
        }
        pendingRestoreRef.current = null;
        if (restoreFallbackTimerRef.current != null) {
          window.clearTimeout(restoreFallbackTimerRef.current);
          restoreFallbackTimerRef.current = null;
        }
        const panel = panelRef.current ?? exitingPanelRef.current;
        exitingPanelRef.current = null;
        if (!focusAlreadyMovedOn(panel)) {
          restoreFocus(...pending);
        }
      }}
    >
      {open ? (
        <motion.button
          key="kern-dialog-backdrop"
          type="button"
          className="kern-dialog-backdrop"
          aria-label="Dismiss dialog"
          disabled={dismissDisabled}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={BACKDROP_TRANSITION}
          onClick={() => {
            if (!dismissDisabled) {
              onDismiss();
            }
          }}
        />
      ) : null}
      {open ? (
        <motion.div
          key="kern-dialog-panel"
          className="kern-dialog-root"
          initial={reduceMotion ? { opacity: 0 } : { opacity: 0, scale: 0.9 }}
          animate={reduceMotion ? { opacity: 1 } : { opacity: 1, scale: 1 }}
          exit={reduceMotion ? { opacity: 0 } : { opacity: 0, scale: 0.9 }}
          transition={reduceMotion ? FADE_ONLY : PANEL_SPRING}
        >
          <div
            ref={(node) => {
              panelRef.current = node;
              if (node) {
                panelNodeRef.current = node;
              }
            }}
            className={["kern-dialog", panelClassName]
              .filter(Boolean)
              .join(" ")}
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            aria-describedby={descriptionId}
            tabIndex={-1}
          >
            {children}
          </div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
