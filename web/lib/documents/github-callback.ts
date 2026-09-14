let capturedGithubCallback: string | null | undefined;

function githubParam(): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  return new URLSearchParams(window.location.search).get("github");
}

export function peekGithubCallback(): string | null {
  return githubParam() || capturedGithubCallback || null;
}

export function captureGithubCallback(): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  const params = new URLSearchParams(window.location.search);
  const github = params.get("github");
  if (github !== null) {
    params.delete("github");
    const query = params.toString();
    const next = `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`;
    window.history.replaceState(null, "", next);
    if (github) {
      capturedGithubCallback = github;
      return github;
    }
  }
  return capturedGithubCallback || null;
}

export function consumeGithubCallback(): void {
  capturedGithubCallback = null;
}
