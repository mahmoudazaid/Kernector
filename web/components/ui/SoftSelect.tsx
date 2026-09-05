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

  useEffect(() => {
    if (!open) {
      return;
    }
    const { options: seededOptions, value: seededValue } = seedRef.current;
    setActiveIndex(indexOfOption(seededOptions, seededValue));
    listRef.current?.focus();
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
