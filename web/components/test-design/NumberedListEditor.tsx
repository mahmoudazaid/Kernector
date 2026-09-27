"use client";

import { useState, type KeyboardEvent } from "react";
import { Reorder, useDragControls } from "motion/react";
import { Button } from "@/components/ui/Button";

type NumberedListEditorProps = {
  /** Singular, capitalized noun used in labels, e.g. "Step". */
  itemLabel: string;
  labelledBy: string;
  items: readonly string[];
  /** Rows kept after removal; 0 lets the list become empty. */
  minItems: number;
  disabled: boolean;
  onChange: (items: string[]) => void;
};

let nextRowId = 0;

function newRowId(): string {
  nextRowId += 1;
  return `row-${nextRowId}`;
}

function GripIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 16 16" width="16" height="16" fill="currentColor">
      <circle cx="5.5" cy="3.5" r="1.25" />
      <circle cx="10.5" cy="3.5" r="1.25" />
      <circle cx="5.5" cy="8" r="1.25" />
      <circle cx="10.5" cy="8" r="1.25" />
      <circle cx="5.5" cy="12.5" r="1.25" />
      <circle cx="10.5" cy="12.5" r="1.25" />
    </svg>
  );
}

type RowProps = {
  id: string;
  index: number;
  total: number;
  value: string;
  itemLabel: string;
  disabled: boolean;
  removeDisabled: boolean;
  onValueChange: (value: string) => void;
  onMove: (index: number, offset: -1 | 1) => void;
  onRemove: () => void;
};

function SortableRow({
  id,
  index,
  total,
  value,
  itemLabel,
  disabled,
  removeDisabled,
  onValueChange,
  onMove,
  onRemove,
}: RowProps) {
  const controls = useDragControls();
  const [dragging, setDragging] = useState(false);
  const noun = itemLabel.toLowerCase();

  function onHandleKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.key === "ArrowUp" && index > 0) {
      event.preventDefault();
      onMove(index, -1);
    } else if (event.key === "ArrowDown" && index < total - 1) {
      event.preventDefault();
      onMove(index, 1);
    }
  }

  return (
    <Reorder.Item
      as="li"
      value={id}
      dragListener={false}
      dragControls={controls}
      className={dragging ? "is-dragging" : undefined}
      onDragStart={() => setDragging(true)}
      onDragEnd={() => setDragging(false)}
    >
      <Button
        type="button"
        variant="ghost"
        className="kern-test-design-case__step-handle"
        disabled={disabled || total < 2}
        aria-label={`Reorder ${noun} ${index + 1}`}
        aria-keyshortcuts="ArrowUp ArrowDown"
        title="Drag to reorder (or use arrow keys)"
        onPointerDown={(event) => {
          if (!disabled && total > 1) {
            controls.start(event);
          }
        }}
        onKeyDown={onHandleKeyDown}
      >
        <GripIcon />
      </Button>
      <input
        className="kern-settings-input kern-test-design-case__step-input"
        type="text"
        value={value}
        disabled={disabled}
        aria-label={`${itemLabel} ${index + 1}`}
        onChange={(event) => onValueChange(event.target.value)}
      />
      <Button
        type="button"
        variant="ghost"
        className="kern-test-design-case__step-remove"
        disabled={removeDisabled}
        aria-label={`Remove ${noun} ${index + 1}`}
        onClick={onRemove}
      >
        Remove
      </Button>
    </Reorder.Item>
  );
}

export function NumberedListEditor({
  itemLabel,
  labelledBy,
  items,
  minItems,
  disabled,
  onChange,
}: NumberedListEditorProps) {
  const [ids, setIds] = useState<string[]>(() => items.map(newRowId));

  let rowIds = ids;
  if (rowIds.length !== items.length) {
    rowIds =
      rowIds.length < items.length
        ? [
            ...rowIds,
            ...Array.from({ length: items.length - rowIds.length }, newRowId),
          ]
        : rowIds.slice(0, items.length);
    setIds(rowIds);
  }

  function commit(nextIds: string[], nextItems: string[]) {
    setIds(nextIds);
    onChange(nextItems);
  }

  function reorder(nextIds: string[]) {
    const textById = new Map(
      rowIds.map((id, index) => [id, items[index] ?? ""]),
    );
    commit(
      nextIds,
      nextIds.map((id) => textById.get(id) ?? ""),
    );
  }

  function move(index: number, offset: -1 | 1) {
    const target = index + offset;
    const nextIds = [...rowIds];
    const nextItems = [...items];
    [nextIds[index], nextIds[target]] = [nextIds[target], nextIds[index]];
    [nextItems[index], nextItems[target]] = [nextItems[target], nextItems[index]];
    commit(nextIds, nextItems);
  }

  function remove(index: number) {
    const nextIds = rowIds.filter((_id, rowIndex) => rowIndex !== index);
    const nextItems = items.filter((_entry, rowIndex) => rowIndex !== index);
    while (nextItems.length < minItems) {
      nextIds.push(newRowId());
      nextItems.push("");
    }
    commit(nextIds, nextItems);
  }

  if (items.length === 0) {
    return null;
  }

  return (
    <Reorder.Group
      as="ol"
      axis="y"
      values={rowIds}
      onReorder={reorder}
      className="kern-test-design-case__steps"
      aria-labelledby={labelledBy}
    >
      {rowIds.map((id, index) => (
        <SortableRow
          key={id}
          id={id}
          index={index}
          total={items.length}
          value={items[index] ?? ""}
          itemLabel={itemLabel}
          disabled={disabled}
          removeDisabled={disabled || (minItems > 0 && items.length <= minItems)}
          onValueChange={(value) => {
            const next = [...items];
            next[index] = value;
            onChange(next);
          }}
          onMove={move}
          onRemove={() => remove(index)}
        />
      ))}
    </Reorder.Group>
  );
}
