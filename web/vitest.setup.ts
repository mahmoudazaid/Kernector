import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { MotionGlobalConfig } from "motion/react";
import { afterEach, vi } from "vitest";
import { consumeDriveCallback } from "@/lib/documents/drive-callback";

MotionGlobalConfig.skipAnimations = true;

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
  cleanup();
});
