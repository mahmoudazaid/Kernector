"use client";

import {
  useEffect,
  useId,
  useRef,
  useState,
  type FocusEvent,
  type KeyboardEvent,
} from "react";

export type SoftSelectProps = {
  id: string;
  label: string;
  value: string;
  options: string[];
  onChange: (value: string) => void;
};

function indexOfOption(options: string[], value: string): number {
  const index = options.indexOf(value);
  return index >= 0 ? index : 0;
}

export function SoftSelect({
  id,
  label,
  value,
  options,
  onChange,
}: SoftSelectProps) {
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(() =>
    indexOfOption(options, value),
  );
  const listId = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const seedRef = useRef({ options, value });
  seedRef.current = { options, value };
  const typeaheadRef = useRef({ buffer: "", at: 0 });

  useEffect(() => {
    if (!open) {
      return;
    }
    const { options: seededOptions, value: seededValue } = seedRef.current;
    setActiveIndex(indexOfOption(seededOptions, seededValue));
    listRef.current?.focus();
    typeaheadRef.current = { buffer: "", at: 0 };
  }, [open]);

  useEffect(() => {
    if (!open) {
      return;
    }
    const option = document.getElementById(`${listId}-${activeIndex}`);
    option?.scrollIntoView?.({ block: "nearest" });
  }, [open, activeIndex, listId]);

  useEffect(() => {
    if (!open) {
      return;
    }

    function onPointerDown(event: PointerEvent) {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    }

    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  function focusTrigger() {
    triggerRef.current?.focus();
  }

  function choose(next: string) {
    onChange(next);
    setOpen(false);
    focusTrigger();
  }

  function onBlur(event: FocusEvent<HTMLDivElement>) {
    if (!rootRef.current?.contains(event.relatedTarget as Node)) {
      setOpen(false);
    }
  }

  function moveActive(delta: number) {
    if (options.length === 0) {
      return;
    }
    setActiveIndex(
      (current) => (current + delta + options.length) % options.length,
    );
  }

  function onTriggerKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (
      event.key === "ArrowDown" ||
      event.key === "ArrowUp" ||
      event.key === "Enter" ||
      event.key === " "
    ) {
      event.preventDefault();
      setOpen(true);
      return;
    }
    if (event.key === "Escape") {
      setOpen(false);
    }
  }

  function onListKeyDown(event: KeyboardEvent<HTMLUListElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      setOpen(false);
      focusTrigger();
      return;
    }

    if (event.key === "ArrowDown") {
      event.preventDefault();
      moveActive(1);
      return;
    }

    if (event.key === "ArrowUp") {
      event.preventDefault();
      moveActive(-1);
      return;
    }

    if (event.key === "Home") {
      event.preventDefault();
      setActiveIndex(0);
      return;
    }

    if (event.key === "End") {
      event.preventDefault();
      setActiveIndex(Math.max(0, options.length - 1));
      return;
    }

    if (options.length === 0) {
      return;
    }

    const typeaheadActive =
      typeaheadRef.current.buffer !== "" &&
      Date.now() - typeaheadRef.current.at <= 700;

    // Space only continues an active typeahead buffer; a standalone Space
    // selects (APG listbox). See https://www.w3.org/WAI/ARIA/apg/patterns/listbox/
    if (
      event.key.length === 1 &&
      (event.key !== " " || typeaheadActive) &&
      !event.metaKey &&
      !event.ctrlKey &&
      !event.altKey
    ) {
      const now = Date.now();
      const typeahead = typeaheadRef.current;
      if (now - typeahead.at > 700) {
        typeahead.buffer = event.key;
      } else if (
        typeahead.buffer.length === 1 &&
        typeahead.buffer === event.key
      ) {
        // Keep a single-character buffer so repeats cycle matches.
      } else {
        typeahead.buffer += event.key;
      }
      typeahead.at = now;
      const needle = typeahead.buffer.toLowerCase();
      const matches = (option: string) => {
        const lower = option.toLowerCase();
        return (
          lower.startsWith(needle) ||
          lower.split("/").some((segment) => segment.startsWith(needle))
        );
      };

      // Repeated single characters cycle from after the active option;
      // a growing buffer re-anchors from the start.
      const start = needle.length === 1 ? activeIndex + 1 : 0;
      const order = Array.from(
        { length: options.length },
        (_, i) => (start + i) % options.length,
      );
      const found = order.find((i) => matches(options[i] ?? "")) ?? -1;
      // Own the key once treated as search — even on a miss — so Space
      // during a live buffer does not scroll the listbox/page.
      event.preventDefault();
      if (found >= 0) {
        setActiveIndex(found);
      }
      return;
    }

    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      const next = options[activeIndex];
      if (next !== undefined) {
        choose(next);
      }
    }
  }

  const activeOptionId =
    open && options.length > 0 ? `${listId}-${activeIndex}` : undefined;

  return (
    <div className="kern-settings-field">
      <label htmlFor={id}>{label}</label>
      <div className="kern-select" ref={rootRef} onBlur={onBlur}>
        <button
          id={id}
          ref={triggerRef}
          type="button"
          className="kern-select-trigger"
          aria-haspopup="listbox"
          aria-expanded={open}
          aria-controls={listId}
          onClick={() => setOpen((current) => !current)}
          onKeyDown={onTriggerKeyDown}
        >
          <span className="kern-select-value">{value}</span>
          <span className="kern-select-chevron" aria-hidden="true" />
        </button>
        {open ? (
          <ul
            ref={listRef}
            id={listId}
            className="kern-select-menu"
            role="listbox"
            tabIndex={-1}
            aria-labelledby={id}
            aria-activedescendant={activeOptionId}
            onKeyDown={onListKeyDown}
          >
            {options.map((option, index) => {
              const selected = option === value;
              const active = index === activeIndex;
              return (
                <li
                  key={option}
                  id={`${listId}-${index}`}
                  role="option"
                  aria-selected={selected}
                  className={[
                    "kern-select-option",
                    selected ? "is-selected" : "",
                    active ? "is-active" : "",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  onClick={() => choose(option)}
                >
                  {option}
                </li>
              );
            })}
          </ul>
        ) : null}
      </div>
    </div>
  );
}
