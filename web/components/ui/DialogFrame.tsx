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

export type DialogFrameProps = {
  open: boolean;
  titleId: string;
  descriptionId?: string;
  panelClassName?: string;
  initialFocusRef?: RefObject<HTMLElement | null>;
  /** When set, focus returns here on close instead of the previously focused node. */
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
  const onDismissRef = useRef(onDismiss);
  onDismissRef.current = onDismiss;
  const dismissDisabledRef = useRef(dismissDisabled);
  dismissDisabledRef.current = dismissDisabled;
  const initialFocusRefStored = useRef(initialFocusRef);
  initialFocusRefStored.current = initialFocusRef;
  const restoreFocusRefStored = useRef(restoreFocusRef);
  restoreFocusRefStored.current = restoreFocusRef;
  const reduceMotion = useReducedMotion();

  useEffect(() => {
    if (!open) {
      return;
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
      const restore = restoreFocusRefStored.current?.current ?? previous;
      restore?.focus();
    };
  }, [open]);

  return (
    <AnimatePresence>
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
            ref={panelRef}
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
