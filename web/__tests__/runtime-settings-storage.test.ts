import { beforeEach, describe, expect, it } from "vitest";
import {
  ACTIVE_SESSION_STORAGE_KEY,
  loadActiveSession,
  saveActiveSession,
} from "@/lib/session/active-session";
import {
  CHAT_MESSAGES_STORAGE_KEY,
  RUNTIME_SETTINGS_STORAGE_KEY,
  loadRuntimeSettings,
  saveRuntimeSettings,
  type StoredRuntimeSettings,
} from "@/lib/settings/runtime-settings-storage";

const SAMPLE: StoredRuntimeSettings = {
  provider: "ollama",
  model: "llama3.2",
  settings: { temperature: 0.5, max_tokens: 800, top_p: 0.9 },
};

describe("runtime settings storage", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("returns null when nothing is stored", () => {
    expect(loadRuntimeSettings()).toBeNull();
  });

  it("round-trips runtime settings under the versioned key", () => {
    saveRuntimeSettings(SAMPLE);

    expect(localStorage.getItem(RUNTIME_SETTINGS_STORAGE_KEY)).toBeTruthy();
    expect(loadRuntimeSettings()).toEqual(SAMPLE);
  });

  it("does not clear session or transcript keys when saving settings", () => {
    localStorage.setItem(
      CHAT_MESSAGES_STORAGE_KEY,
      JSON.stringify([{ id: "1", role: "user", content: "hi" }]),
    );
    saveActiveSession({
      draft: "d",
      messages: [],
      updatedAt: 1,
    });

    saveRuntimeSettings(SAMPLE);

    expect(localStorage.getItem(CHAT_MESSAGES_STORAGE_KEY)).toBeTruthy();
    expect(localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY)).toBeTruthy();
    expect(loadRuntimeSettings()).toEqual(SAMPLE);
  });

  it("ignores malformed JSON", () => {
    localStorage.setItem(RUNTIME_SETTINGS_STORAGE_KEY, "{not-json");
    expect(loadRuntimeSettings()).toBeNull();
  });

  it("ignores payloads missing required fields", () => {
    localStorage.setItem(
      RUNTIME_SETTINGS_STORAGE_KEY,
      JSON.stringify({ provider: "openrouter" }),
    );
    expect(loadRuntimeSettings()).toBeNull();
  });
});

describe("session store owns transcript persistence", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("round-trips messages and clears independently of runtime settings", () => {
    saveRuntimeSettings(SAMPLE);
    const stamp = saveActiveSession({
      draft: "",
      messages: [{ id: "1", role: "user", content: "hi" }],
      updatedAt: 1,
    });

    expect(loadActiveSession().messages).toEqual([
      { id: "1", role: "user", content: "hi" },
    ]);
    saveActiveSession({
      draft: "",
      messages: [],
      updatedAt: stamp!,
    });
    expect(loadActiveSession().messages).toEqual([]);
    expect(loadRuntimeSettings()).toEqual(SAMPLE);
  });

  it("degrades garbage transcripts to an empty list", () => {
    localStorage.setItem(CHAT_MESSAGES_STORAGE_KEY, "{not-json");
    expect(loadActiveSession().messages).toEqual([]);
    localStorage.setItem(
      CHAT_MESSAGES_STORAGE_KEY,
      JSON.stringify([{ role: "user" }]),
    );
    expect(loadActiveSession().messages).toEqual([]);
  });
});
