/**
 * Client helpers for the Test Design chat handoff (#293).
 *
 * The ask wire may include an optional `source_locator` for chip sync; the
 * server reparses `query` and rejects mismatches. Chat never trusts the chip alone.
 */

export type TestDesignSourceLocator = {
  provider: string;
  locator: string;
};

export type TestDesignHandoff = {
  source_locator: TestDesignSourceLocator;
};

/**
 * Build a handoff payload when a canonical GitHub Issue locator is present.
 */
export function buildTestDesignHandoff(
  locator: string | null,
): TestDesignHandoff | null {
  if (locator === null) {
    return null;
  }
  const trimmed = locator.trim();
  if (!trimmed || /^\d+$/u.test(trimmed)) {
    return null;
  }
  return {
    source_locator: { provider: "github", locator: trimmed },
  };
}

export function softwareDeliveryPackEnabled(
  enabledPacks: readonly string[] | null | undefined,
): boolean {
  return Array.isArray(enabledPacks) && enabledPacks.includes("software-delivery");
}
