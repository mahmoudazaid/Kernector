"use client";

import {
  createContext,
  useCallback,
  useContext,
  useId,
  useMemo,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";

type AccordionContextValue = {
  type: "single" | "multiple";
  openValues: Set<string>;
  toggle: (value: string) => void;
};

const AccordionContext = createContext<AccordionContextValue | null>(null);

function useAccordionContext(): AccordionContextValue {
  const ctx = useContext(AccordionContext);
  if (!ctx) {
    throw new Error("Accordion components must be used within Accordion");
  }
  return ctx;
}

export type AccordionProps = {
  type?: "single" | "multiple";
  /** Controlled open values (single: 0–1 entry). */
  value?: string[];
  defaultValue?: string[];
  onValueChange?: (value: string[]) => void;
  className?: string;
  children?: ReactNode;
};

/**
 * Accessible accordion following the shadcn/Radix Accordion pattern without
 * adding a Radix dependency.
 */
export function Accordion({
  type = "multiple",
  value,
  defaultValue = [],
  onValueChange,
  className,
  children,
}: AccordionProps) {
  const [uncontrolled, setUncontrolled] = useState(() => new Set(defaultValue));
  const controlled = value !== undefined;
  const openValues = useMemo(
    () => (controlled ? new Set(value) : uncontrolled),
    [controlled, uncontrolled, value],
  );

  const toggle = useCallback(
    (itemValue: string) => {
      const next = new Set(openValues);
      const isOpen = next.has(itemValue);
      if (type === "single") {
        next.clear();
        if (!isOpen) {
          next.add(itemValue);
        }
      } else if (isOpen) {
        next.delete(itemValue);
      } else {
        next.add(itemValue);
      }
      const list = [...next];
      if (!controlled) {
        setUncontrolled(next);
      }
      onValueChange?.(list);
    },
    [controlled, onValueChange, openValues, type],
  );

  const context = useMemo(
    () => ({ type, openValues, toggle }),
    [openValues, toggle, type],
  );

  return (
    <AccordionContext.Provider value={context}>
      <div className={["kern-accordion", className].filter(Boolean).join(" ")}>
        {children}
      </div>
    </AccordionContext.Provider>
  );
}

export type AccordionItemProps = {
  value: string;
  className?: string;
  children?: ReactNode;
};

const AccordionItemContext = createContext<{
  value: string;
  triggerId: string;
  contentId: string;
} | null>(null);

export function AccordionItem({
  value,
  className,
  children,
}: AccordionItemProps) {
  const autoId = useId();
  const { openValues } = useAccordionContext();
  const item = useMemo(
    () => ({
      value,
      triggerId: `${autoId}-trigger`,
      contentId: `${autoId}-content`,
    }),
    [autoId, value],
  );
  return (
    <AccordionItemContext.Provider value={item}>
      <div
        className={["kern-accordion-item", className].filter(Boolean).join(" ")}
        data-state={openValues.has(value) ? "open" : "closed"}
      >
        {children}
      </div>
    </AccordionItemContext.Provider>
  );
}

function useAccordionItem() {
  const item = useContext(AccordionItemContext);
  if (!item) {
    throw new Error("AccordionTrigger/Content must be used within AccordionItem");
  }
  return item;
}

export type AccordionTriggerProps = {
  className?: string;
  children?: ReactNode;
};

export function AccordionTrigger({
  className,
  children,
}: AccordionTriggerProps) {
  const { openValues, toggle } = useAccordionContext();
  const item = useAccordionItem();
  const open = openValues.has(item.value);

  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      toggle(item.value);
    }
  }

  return (
    <h3 className="kern-accordion-heading">
      <button
        type="button"
        id={item.triggerId}
        className={["kern-accordion-trigger", className]
          .filter(Boolean)
          .join(" ")}
        aria-expanded={open}
        aria-controls={item.contentId}
        data-state={open ? "open" : "closed"}
        onClick={() => {
          toggle(item.value);
        }}
        onKeyDown={onKeyDown}
      >
        {children}
        <svg
          className="kern-accordion-chevron"
          viewBox="0 0 20 20"
          fill="none"
          aria-hidden="true"
        >
          <path
            d="M5 7.5 10 12.5 15 7.5"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>
    </h3>
  );
}

export type AccordionContentProps = {
  className?: string;
  children?: ReactNode;
};

export function AccordionContent({
  className,
  children,
}: AccordionContentProps) {
  const { openValues } = useAccordionContext();
  const item = useAccordionItem();
  const open = openValues.has(item.value);
  if (!open) {
    return null;
  }
  return (
    <div
      id={item.contentId}
      role="region"
      aria-labelledby={item.triggerId}
      className={["kern-accordion-content", className]
        .filter(Boolean)
        .join(" ")}
      data-state="open"
    >
      {children}
    </div>
  );
}
