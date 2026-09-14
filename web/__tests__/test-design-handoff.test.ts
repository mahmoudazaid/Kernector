import { describe, expect, it } from "vitest";
import {
  buildTestDesignHandoff,
  softwareDeliveryPackEnabled,
  ticketIdentifierFromFileName,
} from "@/lib/chat/test-design-handoff";

describe("test-design-handoff", () => {
  it("derives ticket ids from file names and rejects bare numbers", () => {
    expect(ticketIdentifierFromFileName("issue-8.md")).toBe("issue-8");
    expect(ticketIdentifierFromFileName("KERN-293.md")).toBe("KERN-293");
    expect(ticketIdentifierFromFileName("8.md")).toBeNull();
    expect(ticketIdentifierFromFileName("  ")).toBeNull();
  });

  it("builds a handoff only when source and non-bare ticket are present", () => {
    expect(
      buildTestDesignHandoff(
        { source_id: "issue:I_1", source_type: "github" },
        "issue-8",
      ),
    ).toEqual({
      source_reference: { source_id: "issue:I_1", source_type: "github" },
      ticket_identifier: "issue-8",
    });
    expect(
      buildTestDesignHandoff(
        { source_id: "issue:I_1", source_type: "github" },
        "8",
      ),
    ).toBeNull();
    expect(buildTestDesignHandoff(null, "issue-8")).toBeNull();
  });

  it("detects the software-delivery pack flag", () => {
    expect(softwareDeliveryPackEnabled(["software-delivery"])).toBe(true);
    expect(softwareDeliveryPackEnabled([])).toBe(false);
    expect(softwareDeliveryPackEnabled(null)).toBe(false);
  });
});
