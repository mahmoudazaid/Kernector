import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { JSDOM } from "jsdom";
import { MotionGlobalConfig } from "motion/react";
import { afterEach, vi } from "vitest";
import { consumeDriveCallback } from "@/lib/documents/drive-callback";
import { consumeJiraCallback } from "@/lib/documents/jira-callback";

MotionGlobalConfig.skipAnimations = true;

// Node 25+ exposes a global `localStorage` that stays undefined unless
// `--localstorage-file` is set. Borrow a real jsdom Storage instance so
// StorageEvent and bare `localStorage` calls keep working.
if (
  typeof globalThis.localStorage === "undefined" ||
  globalThis.localStorage == null
) {
  const storage = new JSDOM("", { url: "http://localhost/" }).window
    .localStorage;
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    enumerable: true,
    value: storage,
  });
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    enumerable: true,
    value: storage,
  });
}

Object.defineProperty(window, "matchMedia", {
  writable: true,
  configurable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  }),
});

Object.defineProperty(URL, "createObjectURL", {
  writable: true,
  configurable: true,
  value: vi.fn(() => "blob:mock-object-url"),
});

Object.defineProperty(URL, "revokeObjectURL", {
  writable: true,
  configurable: true,
  value: vi.fn(),
});

afterEach(() => {
  consumeDriveCallback();
  consumeJiraCallback();
  cleanup();
});
