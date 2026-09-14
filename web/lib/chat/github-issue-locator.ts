/**
 * Display-only GitHub Issue locator parsing for the Chat composer chip.
 * The backend reparses `query` and is authoritative.
 */

const OWNER_REPO = "([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)";
const URL_RE = new RegExp(
  `https?://(?:www\\.)?github\\.com/${OWNER_REPO}/issues/(\\d+)\\b`,
  "gi",
);
const HASH_RE = new RegExp(`\\b${OWNER_REPO}#(\\d+)\\b`, "g");

export type ParsedGitHubIssueLocator = {
  owner: string;
  repo: string;
  number: number;
  canonical: string;
};

function fromParts(
  owner: string,
  repo: string,
  number: number,
): ParsedGitHubIssueLocator {
  return {
    owner,
    repo,
    number,
    canonical: `${owner}/${repo}#${number}`,
  };
}

function keyOf(item: ParsedGitHubIssueLocator): string {
  return `${item.owner.toLowerCase()}/${item.repo.toLowerCase()}#${item.number}`;
}

/**
 * Extract exactly one Issue from free text for chip display.
 * Duplicate same-Issue mentions are OK; distinct multi-refs return null.
 */
export function extractGitHubIssueLocator(
  text: string,
): ParsedGitHubIssueLocator | null {
  if (!text.trim()) {
    return null;
  }
  const found: ParsedGitHubIssueLocator[] = [];
  for (const pattern of [URL_RE, HASH_RE]) {
    pattern.lastIndex = 0;
    let match: RegExpExecArray | null;
    while ((match = pattern.exec(text)) !== null) {
      found.push(fromParts(match[1], match[2], Number(match[3])));
    }
  }
  if (found.length === 0) {
    return null;
  }
  const unique = new Map<string, ParsedGitHubIssueLocator>();
  for (const item of found) {
    unique.set(keyOf(item), item);
  }
  if (unique.size !== 1) {
    return null;
  }
  return unique.values().next().value ?? null;
}
