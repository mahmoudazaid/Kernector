import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TestDesignWorkspace } from "@/components/test-design/TestDesignWorkspace";
import { ApiError } from "@/lib/api/errors";
import type { RuntimeSettingsResponse } from "@/lib/api/settings";
import {
  exportTestDesignGoogleDrive,
  getTestDesignDraft,
  patchTestDesignDraft,
  type TestCoverageDraftResponse,
} from "@/lib/api/test-design";
import { SETTINGS_CATALOG_UNAVAILABLE } from "@/lib/settings/use-runtime-catalog";

const push = vi.fn();
const reload = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

vi.mock("@/lib/api/test-design", () => ({
  exportTestDesignGoogleDrive: vi.fn(),
  getTestDesignDraft: vi.fn(),
  patchTestDesignDraft: vi.fn(),
}));

vi.mock("@/components/documents/GoogleDrivePicker", () => ({
  GoogleDrivePicker: ({
    open,
    onConfirm,
    onCancel,
    title,
    confirmLabel = "Export",
  }: {
    open: boolean;
    onConfirm: (selection: {
      folders: { id: string; name: string }[];
      files: { id: string; name: string }[];
    }) => void;
    onCancel: () => void;
    title?: string;
    confirmLabel?: string;
  }) =>
    open ? (
      <div role="dialog" aria-label={title ?? "picker"}>
        <h2>{title}</h2>
        <button
          type="button"
          onClick={() =>
            onConfirm({
              folders: [{ id: "folderExport123", name: "Exports" }],
              files: [],
            })
          }
        >
          {confirmLabel}
        </button>
        <button type="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    ) : null,
}));

const runtimeCatalogState = vi.hoisted(() => ({
  catalog: null as RuntimeSettingsResponse | null,
  error: null as string | null,
  loading: false,
  reload: vi.fn(),
}));

vi.mock("@/lib/settings/use-runtime-catalog", async () => {
  const actual = await vi.importActual<typeof import("@/lib/settings/use-runtime-catalog")>(
    "@/lib/settings/use-runtime-catalog",
  );
  return {
    ...actual,
    useRuntimeCatalog: () => runtimeCatalogState,
  };
});

const ENABLED_CATALOG: RuntimeSettingsResponse = {
  providers: ["openrouter"],
  default_provider: "openrouter",
  openrouter: { models: [], default_model: null },
  ollama: { default_base_url: null, default_model: null },
  model_settings: [],
  enabled_packs: ["software-delivery"],
  constraints: {
    max_input_length: 10_000,
    max_upload_bytes: 5_242_880,
    supported_upload_suffixes: [".md", ".pdf", ".txt"],
  },
  short_term_memory_enabled: false,
};

const DISABLED_CATALOG: RuntimeSettingsResponse = {
  ...ENABLED_CATALOG,
  enabled_packs: [],
};

function candidate(
  overrides: Partial<TestCoverageDraftResponse["candidates"][number]> = {},
): TestCoverageDraftResponse["candidates"][number] {
  return {
    candidate_id: "cand-positive",
    title: "Covers happy path",
    category: "positive",
    rationale: "Primary flow",
    evidence_references: [],
    selected: true,
    origin: "suggested",
    ...overrides,
  };
}

function draft(
  overrides: Partial<TestCoverageDraftResponse> = {},
): TestCoverageDraftResponse {
  return {
    draft_id: "draft-1",
    workspace_id: "default",
    conversation_id: "conv-1",
    ticket_identifier: "mahmoudazaid/Kernector#293",
    status: "coverage_review",
    candidates: [
      candidate(),
      candidate({
        candidate_id: "manual-1",
        title: "Manual edge case",
        category: "edge_case",
        origin: "manual",
      }),
    ],
    selected_candidate_ids: ["cand-positive", "manual-1"],
    source_reference: { source_id: "issue-293", source_type: "github_issue" },
    version: 3,
    ...overrides,
  };
}

async function renderWorkspace() {
  render(<TestDesignWorkspace apiBaseUrl="http://api.test" draftId="draft-1" />);
  expect(await screen.findByDisplayValue("Covers happy path")).toBeInTheDocument();
}

describe("TestDesignWorkspace", () => {
  beforeEach(() => {
    push.mockReset();
    reload.mockReset();
    runtimeCatalogState.catalog = ENABLED_CATALOG;
    runtimeCatalogState.error = null;
    runtimeCatalogState.loading = false;
    runtimeCatalogState.reload = reload;
    vi.mocked(getTestDesignDraft).mockReset();
    vi.mocked(patchTestDesignDraft).mockReset();
    vi.mocked(exportTestDesignGoogleDrive).mockReset();
    vi.mocked(getTestDesignDraft).mockResolvedValue(draft());
    vi.mocked(patchTestDesignDraft).mockResolvedValue(draft({ version: 4 }));
    vi.mocked(exportTestDesignGoogleDrive).mockResolvedValue({
      file_id: "drive-1",
      file_name: "mahmoudazaid-Kernector-293.md",
    });
  });

  it("removes manually added blank candidates without losing other edits", async () => {
    const user = userEvent.setup();
    await renderWorkspace();

    const suggestedTitle = screen.getByDisplayValue("Covers happy path");
    await user.clear(suggestedTitle);
    await user.type(suggestedTitle, "Edited happy path");
    await user.click(screen.getByRole("button", { name: /add edge case test/i }));
    await user.click(screen.getByRole("button", { name: /save draft/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /every candidate needs a title/i,
    );

    await user.click(screen.getAllByRole("button", { name: /remove candidate/i }).at(-1)!);
    expect(screen.getByDisplayValue("Edited happy path")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /save draft/i }));

    expect(screen.queryByDisplayValue("")).not.toBeInTheDocument();
    expect(patchTestDesignDraft).toHaveBeenCalledWith(
      expect.objectContaining({
        body: expect.objectContaining({
          candidates: expect.not.arrayContaining([
            expect.objectContaining({ title: "" }),
          ]),
        }),
      }),
    );
  });

  it("does not allow suggested candidates to be removed", async () => {
    await renderWorkspace();

    const suggested = screen.getByDisplayValue("Covers happy path").closest("li");
    expect(suggested).not.toBeNull();
    expect(
      within(suggested!).queryByRole("button", { name: /remove candidate/i }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /keep covers happy path/i })).toBeInTheDocument();
  });

  it("exports selected drafts after choosing a Drive folder", async () => {
    const user = userEvent.setup();
    await renderWorkspace();

    await user.click(screen.getByRole("button", { name: /export to google drive/i }));
    await user.click(screen.getByRole("button", { name: /^export$/i }));

    expect(exportTestDesignGoogleDrive).toHaveBeenCalledWith(
      expect.objectContaining({
        draftId: "draft-1",
        body: { folder_id: "folderExport123" },
      }),
    );
    expect(
      await screen.findByText(/exported mahmoudazaid-kernector-293\.md to exports/i),
    ).toBeInTheDocument();
  });

  it("shows an error when export fails", async () => {
    const user = userEvent.setup();
    vi.mocked(exportTestDesignGoogleDrive).mockRejectedValueOnce(
      new ApiError({
        status: 500,
        title: "Tool failure",
        detail: "Tool failure.",
        code: "tool_failure",
      }),
    );
    await renderWorkspace();

    await user.click(screen.getByRole("button", { name: /export to google drive/i }));
    await user.click(screen.getByRole("button", { name: /^export$/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /could not export to google drive/i,
    );
  });

  it("disables candidate title and selection controls while save is in flight", async () => {
    const user = userEvent.setup();
    let resolvePatch: ((value: ReturnType<typeof draft>) => void) | undefined;
    vi.mocked(patchTestDesignDraft).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolvePatch = resolve;
        }),
    );
    await renderWorkspace();

    const title = screen.getByDisplayValue("Covers happy path");
    const checkbox = screen.getByRole("checkbox", { name: /keep covers happy path/i });
    await user.clear(title);
    await user.type(title, "Edited while idle");
    await user.click(screen.getByRole("button", { name: /save draft/i }));

    expect(title).toBeDisabled();
    expect(checkbox).toBeDisabled();

    resolvePatch?.(
      draft({
        version: 4,
        candidates: [
          candidate({ title: "Edited while idle" }),
          candidate({
            candidate_id: "manual-1",
            title: "Manual edge case",
            category: "edge_case",
            origin: "manual",
          }),
        ],
      }),
    );
    await waitFor(() => {
      expect(screen.getByDisplayValue("Edited while idle")).toBeEnabled();
    });
    expect(screen.getByRole("checkbox", { name: /keep covers happy path|keep edited while idle/i })).toBeEnabled();
  });

  it("demotes ready to coverage_review after saving a title edit", async () => {
    const user = userEvent.setup();
    vi.mocked(getTestDesignDraft).mockResolvedValueOnce(
      draft({ status: "ready", version: 5 }),
    );
    vi.mocked(patchTestDesignDraft).mockResolvedValueOnce(
      draft({
        status: "coverage_review",
        version: 6,
        candidates: [candidate({ title: "Edited after confirm" }), candidate({
          candidate_id: "manual-1",
          title: "Manual edge case",
          category: "edge_case",
          origin: "manual",
        })],
      }),
    );
    await renderWorkspace();

    const title = screen.getByDisplayValue("Covers happy path");
    await user.clear(title);
    await user.type(title, "Edited after confirm");
    await user.click(screen.getByRole("button", { name: /save draft/i }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /export to google drive/i })).toBeEnabled();
    });
    expect(patchTestDesignDraft).toHaveBeenCalled();
  });

  it("records coverage confirmation into the originating conversation on export", async () => {
    const user = userEvent.setup();
    const {
      createConversation,
      getConversation,
      resetConversationsSnapshotForTests,
      CONVERSATIONS_STORAGE_KEY,
    } = await import("@/lib/session/conversations");
    localStorage.clear();
    resetConversationsSnapshotForTests();
    const created = createConversation({
      title: "Design",
      messages: [
        {
          id: "a1",
          role: "assistant",
          content: "Your Test Design draft is ready.",
          action: {
            kind: "open_workflow",
            workflow_id: "software-delivery.test-design",
            label: "Open Test Design",
            draft_id: "draft-1",
          },
        },
      ],
      draft: "",
    });
    const raw = JSON.parse(localStorage.getItem(CONVERSATIONS_STORAGE_KEY)!);
    raw.conversations[0].id = "conv-1";
    localStorage.setItem(CONVERSATIONS_STORAGE_KEY, JSON.stringify(raw));
    resetConversationsSnapshotForTests();
    expect(getConversation("conv-1")?.id).toBe("conv-1");
    expect(created.id).toBeTruthy();

    await renderWorkspace();
    await user.click(screen.getByRole("button", { name: /export to google drive/i }));
    await user.click(screen.getByRole("button", { name: /^export$/i }));

    await waitFor(() => {
      expect(getConversation("conv-1")?.messages[0]?.content).toBe(
        "Coverage confirmed for mahmoudazaid/Kernector#293: 2 tests selected.",
      );
    });
  });

  it("disables export without a selection, while busy, and while dirty", async () => {
    const user = userEvent.setup();
    vi.mocked(getTestDesignDraft).mockResolvedValueOnce(
      draft({
        candidates: [candidate({ selected: false })],
        selected_candidate_ids: [],
      }),
    );
    await renderWorkspace();

    expect(screen.getByRole("button", { name: /export to google drive/i })).toBeDisabled();

    await user.click(screen.getByRole("checkbox", { name: /keep covers happy path/i }));
    expect(screen.getByRole("button", { name: /export to google drive/i })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: /save draft/i }));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /export to google drive/i })).toBeEnabled();
    });
  });


  it("shows loading while runtime settings load", () => {
    runtimeCatalogState.catalog = null;
    runtimeCatalogState.loading = true;

    render(<TestDesignWorkspace apiBaseUrl="http://api.test" draftId="draft-1" />);

    expect(screen.getByText(/loading test design/i)).toBeInTheDocument();
  });

  it("shows retry when runtime settings fail to load", async () => {
    const user = userEvent.setup();
    runtimeCatalogState.catalog = null;
    runtimeCatalogState.error = SETTINGS_CATALOG_UNAVAILABLE;

    render(<TestDesignWorkspace apiBaseUrl="http://api.test" draftId="draft-1" />);

    expect(screen.getByText(/settings catalog unavailable/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^retry$/i }));
    expect(reload).toHaveBeenCalledOnce();
  });

  it("shows pack enablement only when settings loaded and the pack is disabled", () => {
    runtimeCatalogState.catalog = DISABLED_CATALOG;

    render(<TestDesignWorkspace apiBaseUrl="http://api.test" draftId="draft-1" />);

    expect(screen.getByText(/enable the software delivery pack/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^retry$/i })).not.toBeInTheDocument();
  });

  it("loads the draft when settings are enabled", async () => {
    await renderWorkspace();

    expect(getTestDesignDraft).toHaveBeenCalledWith(
      expect.objectContaining({ baseUrl: "http://api.test", draftId: "draft-1" }),
    );
    expect(screen.getByDisplayValue("Covers happy path")).toBeInTheDocument();
  });
});
