"use client";

import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import { formatTimestamp } from "@/lib/format/timestamp";

const WEEKDAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"] as const;
const MONTH_LABELS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
] as const;

export type SoftDatePickerProps = {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  min?: string;
  max?: string;
  disabled?: boolean;
  /** Omit the visible label; ``label`` still names the combobox. */
  hideLabel?: boolean;
  placeholder?: string;
};

function parseYmd(value: string): { y: number; m: number; d: number } | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value.trim());
  if (!match) return null;
  const y = Number(match[1]);
  const m = Number(match[2]);
  const d = Number(match[3]);
  if (!y || m < 1 || m > 12 || d < 1 || d > 31) return null;
  const check = new Date(y, m - 1, d);
  if (
    check.getFullYear() !== y ||
    check.getMonth() !== m - 1 ||
    check.getDate() !== d
  ) {
    return null;
  }
  return { y, m, d };
}

function toYmd(y: number, m: number, d: number): string {
  return `${String(y).padStart(4, "0")}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}

function formatDay(ymd: string): string {
  return formatTimestamp(`${ymd}T12:00:00`).replace(/,.*$/, "");
}

function daysInMonth(y: number, m: number): number {
  return new Date(y, m, 0).getDate();
}

/** Monday-first weekday index 0..6 for the 1st of the month. */
function mondayFirstOffset(y: number, m: number): number {
  const sundayFirst = new Date(y, m - 1, 1).getDay();
  return (sundayFirst + 6) % 7;
}

export function SoftDatePicker({
  id,
  label,
  value,
  onChange,
  min,
  max,
  disabled = false,
  hideLabel = false,
  placeholder = "Select date",
}: SoftDatePickerProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const panelId = useId();
  const parsed = parseYmd(value);
  const minParsed = min ? parseYmd(min) : null;
  const maxParsed = max ? parseYmd(max) : null;
  const initialMonth = parsed
    ? { y: parsed.y, m: parsed.m }
    : minParsed
      ? { y: minParsed.y, m: minParsed.m }
      : (() => {
          const now = new Date();
          return { y: now.getFullYear(), m: now.getMonth() + 1 };
        })();
  const [view, setView] = useState(initialMonth);

  useEffect(() => {
    if (!open || !parsed) return;
    setView({ y: parsed.y, m: parsed.m });
  }, [open, parsed?.y, parsed?.m]);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: MouseEvent) {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    function onKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const cells = useMemo(() => {
    const offset = mondayFirstOffset(view.y, view.m);
    const count = daysInMonth(view.y, view.m);
    const items: Array<{ key: string; ymd: string | null; day: number | null }> =
      [];
    for (let i = 0; i < offset; i += 1) {
      items.push({ key: `pad-${i}`, ymd: null, day: null });
    }
    for (let day = 1; day <= count; day += 1) {
      const ymd = toYmd(view.y, view.m, day);
      items.push({ key: ymd, ymd, day });
    }
    return items;
  }, [view.y, view.m]);

  const display = parsed ? formatDay(value) : placeholder;

  function isOutOfRange(ymd: string): boolean {
    if (min && ymd < min) return true;
    if (max && ymd > max) return true;
    return false;
  }

  function choose(ymd: string) {
    if (isOutOfRange(ymd)) return;
    onChange(ymd);
    setOpen(false);
  }

  function shiftMonth(delta: number) {
    setView((current) => {
      const date = new Date(current.y, current.m - 1 + delta, 1);
      return { y: date.getFullYear(), m: date.getMonth() + 1 };
    });
  }

  function onTriggerKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (
      event.key === "ArrowDown" ||
      event.key === "Enter" ||
      event.key === " "
    ) {
      event.preventDefault();
      if (!disabled) setOpen(true);
    }
  }

  const select = (
    <div className="kern-select kern-date" ref={rootRef}>
      <button
        id={id}
        type="button"
        role="combobox"
        className="kern-select-trigger kern-date-trigger"
        aria-label={hideLabel ? label : undefined}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={panelId}
        disabled={disabled}
        onClick={() => {
          if (!disabled) setOpen((current) => !current);
        }}
        onKeyDown={onTriggerKeyDown}
      >
        <span
          className={`kern-select-value${parsed ? "" : " is-placeholder"}`}
        >
          {display}
        </span>
        <span className="kern-select-chevron" aria-hidden="true" />
      </button>
      {open ? (
        <div
          id={panelId}
          className="kern-date-panel"
          role="dialog"
          aria-label={label}
        >
          <div className="kern-date-toolbar">
            <button
              type="button"
              className="kern-btn kern-btn-ghost kern-date-nav"
              aria-label="Previous month"
              onClick={() => shiftMonth(-1)}
            >
              ‹
            </button>
            <p className="kern-date-month">
              {MONTH_LABELS[view.m - 1]} {view.y}
            </p>
            <button
              type="button"
              className="kern-btn kern-btn-ghost kern-date-nav"
              aria-label="Next month"
              onClick={() => shiftMonth(1)}
            >
              ›
            </button>
          </div>
          <div className="kern-date-weekdays" aria-hidden="true">
            {WEEKDAYS.map((day) => (
              <span key={day}>{day}</span>
            ))}
          </div>
          <div className="kern-date-grid" role="grid">
            {cells.map((cell) => {
              if (!cell.ymd || cell.day === null) {
                return (
                  <span key={cell.key} className="kern-date-cell is-empty" />
                );
              }
              const outOfRange = isOutOfRange(cell.ymd);
              const selected = cell.ymd === value;
              return (
                <button
                  key={cell.key}
                  type="button"
                  className={[
                    "kern-date-cell",
                    selected ? "is-selected" : "",
                    outOfRange ? "is-disabled" : "",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  data-ymd={cell.ymd}
                  disabled={outOfRange}
                  aria-pressed={selected}
                  aria-label={formatDay(cell.ymd)}
                  onClick={() => choose(cell.ymd!)}
                >
                  {cell.day}
                </button>
              );
            })}
          </div>
        </div>
      ) : null}
    </div>
  );

  if (hideLabel) {
    return select;
  }

  return (
    <div className="kern-settings-field">
      <label htmlFor={id}>{label}</label>
      {select}
    </div>
  );
}
