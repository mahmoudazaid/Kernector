let capturedJiraCallback: string | null | undefined;

function jiraParam(): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  return new URLSearchParams(window.location.search).get("jira");
}

export function peekJiraCallback(): string | null {
  return jiraParam() || capturedJiraCallback || null;
}

export function captureJiraCallback(): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  const params = new URLSearchParams(window.location.search);
  const jira = params.get("jira");
  if (jira !== null) {
    params.delete("jira");
    const query = params.toString();
    const next = `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`;
    window.history.replaceState(null, "", next);
    if (jira) {
      capturedJiraCallback = jira;
      return jira;
    }
  }
  return capturedJiraCallback || null;
}

export function consumeJiraCallback(): void {
  capturedJiraCallback = null;
}
