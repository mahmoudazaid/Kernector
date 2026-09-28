import { afterEach, describe, expect, it } from "vitest";
import {
  captureJiraCallback,
  consumeJiraCallback,
  peekJiraCallback,
} from "@/lib/documents/jira-callback";

afterEach(() => {
  consumeJiraCallback();
  window.history.replaceState(null, "", "/documents");
});

describe("jira callback query helper", () => {
  it("captures and clears the jira query param, keeping others", () => {
    window.history.replaceState(null, "", "/documents?jira=no_site&tab=sources");
    expect(captureJiraCallback()).toBe("no_site");
    expect(window.location.search).toBe("?tab=sources");
    expect(peekJiraCallback()).toBe("no_site");
    consumeJiraCallback();
    expect(peekJiraCallback()).toBeNull();
  });

  it("ignores an empty jira param", () => {
    window.history.replaceState(null, "", "/documents?jira=");
    expect(captureJiraCallback()).toBeNull();
  });
});
