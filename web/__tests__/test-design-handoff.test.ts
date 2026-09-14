import { describe, expect, it } from "vitest";
import {
  buildTestDesignHandoff,
  softwareDeliveryPackEnabled,
} from "@/lib/chat/test-design-handoff";
import { extractGitHubIssueLocator } from "@/lib/chat/github-issue-locator";

describe("test-design-handoff", () => {
  it("builds a handoff from a canonical GitHub Issue locator", () => {
    expect(buildTestDesignHandoff("mahmoudazaid/Kernector#293")).toEqual({
      source_locator: {
        provider: "github",
        locator: "mahmoudazaid/Kernector#293",
      },
    });
    expect(buildTestDesignHandoff("293")).toBeNull();
    expect(buildTestDesignHandoff(null)).toBeNull();
  });

  it("parses issue URLs and owner/repo#N for the display chip", () => {
    expect(
      extractGitHubIssueLocator(
        "Design tests for https://github.com/mahmoudazaid/Kernector/issues/293",
      )?.canonical,
    ).toBe("mahmoudazaid/Kernector#293");
    expect(
      extractGitHubIssueLocator(
        "Design tests for mahmoudazaid/Kernector#293 and again mahmoudazaid/Kernector#293",
      )?.canonical,
    ).toBe("mahmoudazaid/Kernector#293");
    expect(
      extractGitHubIssueLocator(
        "Design tests for mahmoudazaid/Kernector#293 and other/repo#1",
      ),
    ).toBeNull();
  });

  it("detects the software-delivery pack flag", () => {
    expect(softwareDeliveryPackEnabled(["software-delivery"])).toBe(true);
    expect(softwareDeliveryPackEnabled([])).toBe(false);
    expect(softwareDeliveryPackEnabled(null)).toBe(false);
  });
});
