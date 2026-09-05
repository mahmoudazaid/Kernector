import { beforeEach, describe, expect, it } from "vitest";
import {
  CHAT_MESSAGES_STORAGE_KEY,
  RUNTIME_SETTINGS_STORAGE_KEY,
  clearChatMessages,
  loadChatMessages,
  loadRuntimeSettings,
  saveChatMessages,
  saveRuntimeSettings,
  type StoredRuntimeSettings,
} from "@/lib/runtime-settings-storage";

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

describe("chat messages storage", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("round-trips messages and clears independently of runtime settings", () => {
    saveRuntimeSettings(SAMPLE);
    saveChatMessages([{ id: "1", role: "user", content: "hi" }]);

    expect(loadChatMessages()).toEqual([{ id: "1", role: "user", content: "hi" }]);
    clearChatMessages();
    expect(loadChatMessages()).toEqual([]);
    expect(localStorage.getItem(CHAT_MESSAGES_STORAGE_KEY)).toBeNull();
    expect(loadRuntimeSettings()).toEqual(SAMPLE);
  });

  it("degrades garbage transcripts to an empty list", () => {
    localStorage.setItem(CHAT_MESSAGES_STORAGE_KEY, "{not-json");
    expect(loadChatMessages()).toEqual([]);
    localStorage.setItem(CHAT_MESSAGES_STORAGE_KEY, JSON.stringify([{ role: "user" }]));
    expect(loadChatMessages()).toEqual([]);
  });
});
