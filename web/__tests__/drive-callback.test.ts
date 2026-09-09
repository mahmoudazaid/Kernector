import { afterEach, describe, expect, it } from "vitest";
import {
  captureDriveCallback,
  consumeDriveCallback,
  peekDriveCallback,
} from "@/lib/documents/drive-callback";

afterEach(() => {
  consumeDriveCallback();
  window.history.replaceState(null, "", "/documents");
});

describe("drive callback query", () => {
  it("ignores an empty drive query", () => {
    window.history.replaceState(null, "", "/documents?drive=");
    expect(peekDriveCallback()).toBeNull();
    expect(captureDriveCallback()).toBeNull();
    expect(window.location.search).toBe("");
  });

  it("captures a real callback and then consumes it", () => {
    window.history.replaceState(null, "", "/documents?drive=connected");
    expect(peekDriveCallback()).toBe("connected");
    expect(captureDriveCallback()).toBe("connected");
    expect(window.location.search).toBe("");
    consumeDriveCallback();
    expect(peekDriveCallback()).toBeNull();
  });
});
