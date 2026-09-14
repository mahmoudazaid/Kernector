"use client";

import type { TestDesignHandoff } from "@/lib/chat/test-design-handoff";

export type ChatIssueLocatorChipProps = {
  handoff: TestDesignHandoff | null;
  onClear: () => void;
  disabled?: boolean;
};

/**
 * Display-only Issue chip (Instrument panel). Backend reparses query.
 */
export function ChatIssueLocatorChip({
  handoff,
  onClear,
  disabled = false,
}: ChatIssueLocatorChipProps) {
  if (handoff === null) {
    return null;
  }
  return (
    <div className="kern-chat-issue-chip" role="status">
      <span className="kern-chat-issue-chip__label">GitHub Issue</span>
      <code className="kern-chat-issue-chip__locator">
        {handoff.source_locator.locator}
      </code>
      <button
        type="button"
        className="kern-chat-issue-chip__clear"
        disabled={disabled}
        aria-label="Remove Issue reference chip"
        onClick={onClear}
      >
        Clear
      </button>
    </div>
  );
}
