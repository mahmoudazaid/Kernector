/**
 * Client helpers for the Test Design chat handoff (#293).
 *
 * The ask wire requires an explicit SourceReference plus a non-bare ticket
 * identifier. Chat never infers these from message prose.
 */

export type TestDesignSourceRef = {
  source_id: string;
  source_type: string;
};

export type TestDesignHandoff = {
  source_reference: TestDesignSourceRef;
  ticket_identifier: string;
};

/**
 * Derive a default ticket id from a catalog file name (e.g. ``issue-8.md`` →
 * ``issue-8``). Returns ``null`` when blank or digits-only (bare numbers are
 * rejected by the server handoff contract).
 */
export function ticketIdentifierFromFileName(fileName: string): string | null {
  const base = fileName.trim().replace(/\.[^.]+$/u, "").trim();
  if (!base || /^\d+$/u.test(base)) {
    return null;
  }
  return base;
}

/**
 * Build a handoff payload when both source and ticket are present and valid.
 */
export function buildTestDesignHandoff(
  source: TestDesignSourceRef | null,
  ticketIdentifier: string,
): TestDesignHandoff | null {
  if (source === null) {
    return null;
  }
  const sourceId = source.source_id.trim();
  const sourceType = source.source_type.trim();
  const ticket = ticketIdentifier.trim();
  if (!sourceId || !sourceType || !ticket || /^\d+$/u.test(ticket)) {
    return null;
  }
  return {
    source_reference: { source_id: sourceId, source_type: sourceType },
    ticket_identifier: ticket,
  };
}

export function softwareDeliveryPackEnabled(
  enabledPacks: readonly string[] | null | undefined,
): boolean {
  return Array.isArray(enabledPacks) && enabledPacks.includes("software-delivery");
}
