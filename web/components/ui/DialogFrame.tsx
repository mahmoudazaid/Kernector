"use client";

import {
  useCallback,
  useEffect,
  useRef,
  type ReactNode,
  type RefObject,
} from "react";
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

/** Page-wide: any dialog chrome (for opener tracking). */
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

/**
 * True when focus has moved outside *this* frame (e.g. into another modal or
 * a fresh alert). Frame-scoped so a closing dialog cannot steal focus from a
 * still-open sibling.
 */
function focusAlreadyMovedOn(
  panel: HTMLElement | null,
  backdrop: HTMLElement | null,
): boolean {
  const active = document.activeElement;
  if (!active || active === document.body) {
    return false;
  }
  // Still on this frame's root (panel or its motion wrapper).
  if (panel?.closest(".kern-dialog-root")?.contains(active)) {
    return false;
  }
  // Still on this frame's backdrop (identity, not class — avoids sibling theft).
  if (backdrop && active === backdrop) {
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
  /** Survives host-ref detach on unmount; cleared when restore is consumed. */
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
  const exitingPanelRef = useRef<HTMLElement | null>(null);
  const restoreFallbackTimerRef = useRef<number | null>(null);
  const reduceMotion = useReducedMotion();

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
      exitingPanelRef.current = null;
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

  useEffect(() => {
    if (!open) {
      return;
    }
    // Cancel a restore still waiting on a previous exit animation.
    pendingRestoreRef.current = null;
    exitingPanelRef.current = null;
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
      // Defer until AnimatePresence exit completes so aria-modal is gone.
      pendingRestoreRef.current = [
        restoreFocusRefStored.current?.current,
        openerRef.current,
        previous,
      ];
      // Prefer panelNodeRef: panelRef is already null on the unmount path.
      const panelAtArm = panelNodeRef.current ?? panelRef.current;
      exitingPanelRef.current = panelAtArm;
      restoreFallbackTimerRef.current = window.setTimeout(() => {
        restoreFallbackTimerRef.current = null;
        consumePendingRestore(panelAtArm);
      }, RESTORE_FALLBACK_MS);
    };
  }, [open, clearRestoreFallbackTimer, consumePendingRestore]);

  // Declared after the [open] effect so destroy order sees an armed restore
  // when the frame unmounts while still open (e.g. Drive picker).
  useEffect(() => {
    return () => {
      consumePendingRestore(exitingPanelRef.current);
    };
  }, [consumePendingRestore]);

  return (
    <AnimatePresence
      onExitComplete={() => {
        consumePendingRestore(panelRef.current ?? exitingPanelRef.current);
      }}
    >
      {open ? (
        <motion.button
          key="kern-dialog-backdrop"
          type="button"
          ref={backdropRef}
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
