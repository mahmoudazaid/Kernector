import { afterEach, describe, expect, it } from "vitest";
import {
  captureGithubCallback,
  consumeGithubCallback,
  peekGithubCallback,
} from "@/lib/documents/github-callback";

afterEach(() => {
  consumeGithubCallback();
  window.history.replaceState(null, "", "/documents");
});

describe("github callback query helper", () => {
  it("captures and clears the github query param", () => {
    window.history.replaceState(null, "", "/documents?github=connected");
    expect(captureGithubCallback()).toBe("connected");
    expect(window.location.search).not.toContain("github=");
    expect(peekGithubCallback()).toBe("connected");
    consumeGithubCallback();
    expect(peekGithubCallback()).toBeNull();
  });

  it("ignores an empty github param after clearing the URL", () => {
    window.history.replaceState(null, "", "/documents?github=");
    expect(captureGithubCallback()).toBeNull();
  });
});
