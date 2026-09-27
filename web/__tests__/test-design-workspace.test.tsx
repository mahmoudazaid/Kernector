import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TestDesignWorkspace } from "@/components/test-design/TestDesignWorkspace";
import { ApiError } from "@/lib/api/errors";
import type { RuntimeSettingsResponse } from "@/lib/api/settings";
import {
  confirmTestDesignDraft,
  exportTestDesignGoogleDrive,
  generateTestDesignCases,
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
  confirmTestDesignDraft: vi.fn(),
  exportTestDesignGoogleDrive: vi.fn(),
  generateTestDesignCases: vi.fn(),
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
    coverage_gaps: [],
    cucumber_feature: "",
    cucumber_background: "",
    generated_cases: [],
    skipped_edited_candidate_ids: [],
    evidence_fingerprint: null,
    source_reference: { source_id: "issue-293", source_type: "github_issue" },
    version: 3,
    ...overrides,
  };
}

async function renderWorkspace() {
  render(<TestDesignWorkspace apiBaseUrl="http://api.test" draftId="draft-1" />);
  expect(await screen.findByDisplayValue("Covers happy path")).toBeInTheDocument();
}

function stepsDraft(
  overrides: Partial<TestCoverageDraftResponse> = {},
): TestCoverageDraftResponse {
  return draft({
    status: "case_editing",
    evidence_fingerprint: "fp-1",
    candidates: [candidate()],
    selected_candidate_ids: ["cand-positive"],
    generated_cases: [
      {
        candidate_id: "cand-positive",
        test_type: "manual",
        automation_fit: "applicable",
        automation_rationale: "Stable path",
        availability: "available",
        preconditions: "Logged out",
        steps: ["Login"],
        expected_result: "Home",
        gherkin: "",
        user_edited: false,
      },
    ],
    ...overrides,
  });
}

async function renderStepsWorkspace() {
  vi.mocked(getTestDesignDraft).mockResolvedValue(stepsDraft());
  render(<TestDesignWorkspace apiBaseUrl="http://api.test" draftId="draft-1" />);
  expect(await screen.findByRole("region", { name: /manual package/i })).toBeInTheDocument();
}

async function saveAndExit(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: /^exit$/i }));
  const dialog = await screen.findByRole("dialog", { name: /leave test design/i });
  await user.click(within(dialog).getByRole("button", { name: /save and exit/i }));
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
    vi.mocked(confirmTestDesignDraft).mockReset();
    vi.mocked(exportTestDesignGoogleDrive).mockReset();
    vi.mocked(generateTestDesignCases).mockReset();
    vi.mocked(getTestDesignDraft).mockResolvedValue(draft());
    vi.mocked(patchTestDesignDraft).mockResolvedValue(draft({ version: 4 }));
    vi.mocked(confirmTestDesignDraft).mockResolvedValue(
      draft({ status: "ready", version: 4 }),
    );
    vi.mocked(generateTestDesignCases).mockResolvedValue(
      draft({
        status: "case_editing",
        version: 5,
        evidence_fingerprint: "fp-1",
        generated_cases: [
          {
            candidate_id: "cand-positive",
            test_type: "manual",
            automation_fit: "applicable",
            automation_rationale: "Stable path",
            availability: "available",
            preconditions: "Logged out",
            steps: ["Login"],
            expected_result: "Home",
            gherkin: "",
            user_edited: false,
          },
        ],
      }),
    );
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
    await saveAndExit(user);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /every candidate needs a title/i,
    );
    expect(push).not.toHaveBeenCalled();

    await user.click(screen.getAllByRole("button", { name: /remove candidate/i }).at(-1)!);
    expect(screen.getByDisplayValue("Edited happy path")).toBeInTheDocument();
    await saveAndExit(user);

    await waitFor(() => expect(push).toHaveBeenCalledWith("/chat/conv-1"));
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

  it("shows Export only on Test steps, and exits without a dialog when nothing changed", async () => {
    const user = userEvent.setup();
    await renderWorkspace();

    expect(
      screen.queryByRole("button", { name: /export to google drive/i }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /save draft/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /back to chat/i })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^exit$/i }));
    expect(screen.queryByRole("dialog", { name: /leave test design/i })).not.toBeInTheDocument();
    expect(push).toHaveBeenCalledWith("/chat/conv-1");
  });

  it("exits without saving, or keeps editing, from the Exit dialog", async () => {
    const user = userEvent.setup();
    await renderWorkspace();
    const title = screen.getByDisplayValue("Covers happy path");
    await user.type(title, " edited");

    await user.click(screen.getByRole("button", { name: /^exit$/i }));
    let dialog = await screen.findByRole("dialog", { name: /leave test design/i });
    await user.click(within(dialog).getByRole("button", { name: /keep editing/i }));
    expect(push).not.toHaveBeenCalled();
    expect(screen.getByDisplayValue("Covers happy path edited")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^exit$/i }));
    dialog = await screen.findByRole("dialog", { name: /leave test design/i });
    await user.click(within(dialog).getByRole("button", { name: /exit without saving/i }));
    expect(push).toHaveBeenCalledWith("/chat/conv-1");
    expect(patchTestDesignDraft).not.toHaveBeenCalled();
  });

  it("exports selected drafts after choosing a Drive folder", async () => {
    const user = userEvent.setup();
    await renderStepsWorkspace();

    await user.click(screen.getByRole("button", { name: /export to google drive/i }));
    await user.click(screen.getByRole("button", { name: /^export$/i }));

    expect(exportTestDesignGoogleDrive).toHaveBeenCalledWith(
      expect.objectContaining({
        draftId: "draft-1",
        body: {
          folder_id: "folderExport123",
          destination_label: "Exports",
        },
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
    await renderStepsWorkspace();

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
    await saveAndExit(user);

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
    await saveAndExit(user);

    await waitFor(() => expect(push).toHaveBeenCalledWith("/chat/conv-1"));
    expect(patchTestDesignDraft).toHaveBeenCalled();
  });

  it("records coverage confirmation and generates cases on Next", async () => {
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
    expect(
      screen.getByRole("navigation", { name: /workflow progress/i }),
    ).toBeInTheDocument();
    const progress = screen.getByRole("navigation", {
      name: /workflow progress/i,
    });
    expect(within(progress).getByText(/^Test selection$/)).toBeInTheDocument();
    expect(within(progress).getByText(/^Test steps$/)).toBeInTheDocument();
    expect(within(progress).queryByText(/^Format$/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^next$/i })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^confirm$/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("group", {
        name: /test type for covers happy path/i,
      }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^next$/i }));

    await waitFor(() => {
      expect(getConversation("conv-1")?.messages[0]?.content).toBe(
        "Coverage confirmed for mahmoudazaid/Kernector#293: 2 tests selected.",
      );
    });
    expect(confirmTestDesignDraft).toHaveBeenCalled();
    expect(generateTestDesignCases).toHaveBeenCalled();
    expect(await screen.findByDisplayValue("Logged out")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^next$/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^generate$/i }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^regenerate$/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^back$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /export to google drive/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^exit$/i })).toBeInTheDocument();
  });

  it("exports without rewriting the conversation card", async () => {
    const user = userEvent.setup();
    const {
      createConversation,
      getConversation,
      resetConversationsSnapshotForTests,
      CONVERSATIONS_STORAGE_KEY,
    } = await import("@/lib/session/conversations");
    localStorage.clear();
    resetConversationsSnapshotForTests();
    createConversation({
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

    await renderStepsWorkspace();
    await user.click(screen.getByRole("button", { name: /export to google drive/i }));
    await user.click(screen.getByRole("button", { name: /^export$/i }));

    await waitFor(() => {
      expect(exportTestDesignGoogleDrive).toHaveBeenCalled();
    });
    expect(getConversation("conv-1")?.messages[0]?.content).toBe(
      "Your Test Design draft is ready.",
    );
  });

  it("auto-saves step edits before opening the export picker", async () => {
    const user = userEvent.setup();
    vi.mocked(patchTestDesignDraft).mockImplementation(async ({ body }) =>
      stepsDraft({
        version: 4,
        generated_cases: body.generated_cases ?? stepsDraft().generated_cases,
      }),
    );
    await renderStepsWorkspace();

    const step = screen.getByLabelText(/^step 1$/i);
    await user.clear(step);
    await user.type(step, "Sign in");
    await user.click(screen.getByRole("button", { name: /export to google drive/i }));

    await waitFor(() => {
      expect(patchTestDesignDraft).toHaveBeenCalledWith(
        expect.objectContaining({
          body: expect.objectContaining({
            generated_cases: [expect.objectContaining({ steps: ["Sign in"] })],
          }),
        }),
      );
    });
    expect(await screen.findByRole("dialog", { name: /export to google drive/i })).toBeInTheDocument();
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

  it("lets confirmed drafts set type and generate cases", async () => {
    const user = userEvent.setup();
    const readyDraft = draft({
      status: "ready",
      evidence_fingerprint: "fp-1",
    });
    vi.mocked(getTestDesignDraft).mockResolvedValue(readyDraft);
    vi.mocked(patchTestDesignDraft).mockImplementation(async ({ body }) => ({
      ...readyDraft,
      version: readyDraft.version + 1,
      candidates: body.candidates ?? readyDraft.candidates,
      generated_cases: body.generated_cases ?? readyDraft.generated_cases,
    }));
    vi.mocked(generateTestDesignCases).mockResolvedValue(
      draft({
        status: "case_editing",
        version: 5,
        evidence_fingerprint: "fp-1",
        generated_cases: [
          {
            candidate_id: "cand-positive",
            test_type: "manual",
            automation_fit: "applicable",
            automation_rationale: "Stable path",
            availability: "available",
            preconditions: "Logged out",
            steps: ["Login"],
            expected_result: "Home",
            gherkin: "",
            user_edited: false,
          },
        ],
      }),
    );

    await renderWorkspace();

    expect(screen.getByRole("button", { name: /^next$/i })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^confirm$/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^generate$/i }),
    ).not.toBeInTheDocument();

    const typeGroup = screen.getByRole("group", {
      name: /test type for covers happy path/i,
    });
    await user.click(within(typeGroup).getByRole("button", { name: /^manual$/i }));
    await user.click(screen.getByRole("button", { name: /^next$/i }));
    await waitFor(() => {
      expect(patchTestDesignDraft).toHaveBeenCalled();
      expect(generateTestDesignCases).toHaveBeenCalledWith(
        expect.objectContaining({
          draftId: "draft-1",
          body: expect.objectContaining({
            overwrite_edited: false,
          }),
        }),
      );
    });
    expect(await screen.findByDisplayValue("Logged out")).toBeInTheDocument();
    expect(screen.getByLabelText(/^test title$/i)).toHaveValue("Covers happy path");
    expect(screen.queryByRole("checkbox", { name: /keep covers happy path/i })).not.toBeInTheDocument();
  });

  it("shows shared Feature and Background once for Cucumber cases", async () => {
    const user = userEvent.setup();
    const editingDraft = draft({
      status: "case_editing",
      evidence_fingerprint: "fp-1",
      cucumber_feature: "Personality selection",
      cucumber_background: "Given the application is running",
      generated_cases: [
        {
          candidate_id: "cand-positive",
          test_type: "cucumber",
          automation_fit: "unclear",
          automation_rationale: "Unclear from ticket alone",
          availability: "available",
          preconditions: "",
          steps: [],
          expected_result: "",
          gherkin: "Given the user selects Friendly",
          user_edited: false,
        },
        {
          candidate_id: "manual-1",
          test_type: "cucumber",
          automation_fit: "unclear",
          automation_rationale: "Unclear from ticket alone",
          availability: "available",
          preconditions: "",
          steps: [],
          expected_result: "",
          gherkin: "Given the user selects Formal",
          user_edited: false,
        },
      ],
    });
    vi.mocked(getTestDesignDraft).mockResolvedValue(editingDraft);
    vi.mocked(patchTestDesignDraft).mockImplementation(async ({ body }) => ({
      ...editingDraft,
      version: editingDraft.version + 1,
      cucumber_feature: body.cucumber_feature ?? editingDraft.cucumber_feature,
      cucumber_background:
        body.cucumber_background ?? editingDraft.cucumber_background,
      generated_cases: body.generated_cases ?? editingDraft.generated_cases,
    }));

    render(<TestDesignWorkspace apiBaseUrl="http://api.test" draftId="draft-1" />);
    expect(await screen.findByDisplayValue("Covers happy path")).toBeInTheDocument();
    expect(screen.getAllByLabelText(/^scenario name$/i)).toHaveLength(2);

    expect(
      screen.getByRole("region", { name: /cucumber package/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: /shared cucumber feature/i }),
    ).toBeInTheDocument();
    expect(screen.getAllByLabelText(/cucumber feature title/i)).toHaveLength(1);
    expect(screen.getAllByLabelText(/cucumber background steps/i)).toHaveLength(1);
    expect(screen.getByDisplayValue("Personality selection")).toBeInTheDocument();
    expect(
      screen.getByDisplayValue("Given the application is running"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/^Gherkin$/)).not.toBeInTheDocument();
    expect(screen.queryByText(/^Scenario$/)).not.toBeInTheDocument();
    expect(
      screen.getByLabelText(/scenario steps for covers happy path/i),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/scenario steps for manual edge case/i)).toBeInTheDocument();

    await user.clear(screen.getByLabelText(/cucumber feature title/i));
    await user.type(
      screen.getByLabelText(/cucumber feature title/i),
      "Agent personality",
    );
    await user.click(screen.getByRole("button", { name: /^back$/i }));

    await waitFor(() => {
      expect(patchTestDesignDraft).toHaveBeenCalledWith(
        expect.objectContaining({
          body: expect.objectContaining({
            cucumber_feature: "Agent personality",
            cucumber_background: "Given the application is running",
          }),
        }),
      );
    });
  });

  it("reorders manual preconditions, steps, and expected results", async () => {
    const user = userEvent.setup();
    const editingDraft = draft({
      status: "case_editing",
      evidence_fingerprint: "fp-1",
      generated_cases: [
        {
          candidate_id: "cand-positive",
          test_type: "manual",
          automation_fit: "applicable",
          automation_rationale: "Stable path",
          availability: "available",
          preconditions: "Logged out\nFeature flag on",
          steps: ["Login", "Open settings", "Save"],
          expected_result: "Home loads\nSettings saved",
          gherkin: "",
          user_edited: false,
        },
      ],
    });
    vi.mocked(getTestDesignDraft).mockResolvedValue(editingDraft);
    vi.mocked(patchTestDesignDraft).mockImplementation(async ({ body }) => ({
      ...editingDraft,
      version: editingDraft.version + 1,
      generated_cases: body.generated_cases ?? editingDraft.generated_cases,
    }));

    render(<TestDesignWorkspace apiBaseUrl="http://api.test" draftId="draft-1" />);
    await screen.findByRole("region", { name: /manual package/i });

    const stepHandle = screen.getByRole("button", { name: /reorder step 3/i });
    stepHandle.focus();
    await user.keyboard("{ArrowUp}");
    expect(screen.getByLabelText(/^step 2$/i)).toHaveValue("Save");
    expect(screen.getByLabelText(/^step 3$/i)).toHaveValue("Open settings");
    expect(stepHandle).toHaveFocus();
    expect(stepHandle).toHaveAccessibleName(/reorder step 2/i);

    screen.getByRole("button", { name: /reorder precondition 1/i }).focus();
    await user.keyboard("{ArrowDown}");
    screen.getByRole("button", { name: /reorder expected result 2/i }).focus();
    await user.keyboard("{ArrowUp}");

    await user.click(screen.getByRole("button", { name: /^back$/i }));
    await waitFor(() => {
      expect(patchTestDesignDraft).toHaveBeenCalledWith(
        expect.objectContaining({
          body: expect.objectContaining({
            generated_cases: [
              expect.objectContaining({
                preconditions: "Feature flag on\nLogged out",
                steps: ["Login", "Save", "Open settings"],
                expected_result: "Settings saved\nHome loads",
              }),
            ],
          }),
        }),
      );
    });
  });

  it("lets the user remove and re-add the shared Cucumber background", async () => {
    const user = userEvent.setup();
    const editingDraft = draft({
      status: "case_editing",
      evidence_fingerprint: "fp-1",
      cucumber_feature: "Personality selection",
      cucumber_background: "Given the application is running",
      candidates: [candidate()],
      selected_candidate_ids: ["cand-positive"],
      generated_cases: [
        {
          candidate_id: "cand-positive",
          test_type: "cucumber",
          automation_fit: "unclear",
          automation_rationale: "Unclear from ticket alone",
          availability: "available",
          preconditions: "",
          steps: [],
          expected_result: "",
          gherkin: "Given the user selects Friendly",
          user_edited: false,
        },
      ],
    });
    vi.mocked(getTestDesignDraft).mockResolvedValue(editingDraft);
    vi.mocked(patchTestDesignDraft).mockImplementation(async ({ body }) => ({
      ...editingDraft,
      version: editingDraft.version + 1,
      cucumber_background:
        body.cucumber_background ?? editingDraft.cucumber_background,
    }));

    render(<TestDesignWorkspace apiBaseUrl="http://api.test" draftId="draft-1" />);
    await user.click(
      await screen.findByRole("button", { name: /remove background/i }),
    );
    expect(
      screen.queryByLabelText(/cucumber background steps/i),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^back$/i }));
    await waitFor(() => {
      expect(patchTestDesignDraft).toHaveBeenCalledWith(
        expect.objectContaining({
          body: expect.objectContaining({ cucumber_background: "" }),
        }),
      );
    });

    await user.click(await screen.findByRole("button", { name: /^next$/i }));
    await user.click(await screen.findByRole("button", { name: /add background/i }));
    const background = screen.getByLabelText(/cucumber background steps/i);
    expect(background).toHaveValue("");
    await user.type(background, "Given a fresh session");
    expect(background).toHaveValue("Given a fresh session");
  });

  it("packages Manual with Preconditions/Steps/Expected Result and parks insufficient evidence", async () => {
    const editingDraft = draft({
      status: "case_editing",
      evidence_fingerprint: "fp-1",
      generated_cases: [
        {
          candidate_id: "cand-positive",
          test_type: "manual",
          automation_fit: "applicable",
          automation_rationale: "Stable path",
          availability: "available",
          preconditions: "1) Logged out",
          steps: ["1) Login", "2) Open settings"],
          expected_result: "1) Home loads\n2) Settings visible",
          gherkin: "",
          user_edited: false,
        },
        {
          candidate_id: "manual-1",
          test_type: "manual",
          automation_fit: "unclear",
          automation_rationale: "Ticket lacks harness detail",
          availability: "insufficient_evidence",
          preconditions: "",
          steps: [],
          expected_result: "",
          gherkin: "",
          user_edited: false,
        },
      ],
    });
    vi.mocked(getTestDesignDraft).mockResolvedValue(editingDraft);

    render(<TestDesignWorkspace apiBaseUrl="http://api.test" draftId="draft-1" />);
    expect(
      await screen.findByRole("region", { name: /manual package/i }),
    ).toBeInTheDocument();
    const clarification = screen.getByRole("region", {
      name: /needs more detail from the ticket/i,
    });
    expect(clarification).toBeInTheDocument();
    expect(
      within(clarification).getByText(/ticket lacks harness detail/i),
    ).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: /cucumber package/i })).not.toBeInTheDocument();

    expect(screen.getByDisplayValue("Logged out")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("1) Logged out")).not.toBeInTheDocument();
    expect(screen.getByLabelText(/^step 1$/i)).toHaveValue("Login");
    expect(screen.getByLabelText(/^step 2$/i)).toHaveValue("Open settings");
    expect(screen.getByLabelText(/^expected result 1$/i)).toHaveValue("Home loads");
    expect(screen.getByLabelText(/^expected result 2$/i)).toHaveValue(
      "Settings visible",
    );
    expect(
      screen.getByText(/no steps were generated, to avoid guessing/i),
    ).toBeInTheDocument();
  });

  describe("cases that need more detail", () => {
    const needsDetailDraft = () =>
      draft({
        status: "case_editing",
        evidence_fingerprint: "fp-1",
        generated_cases: [
          {
            candidate_id: "cand-positive",
            test_type: "manual",
            automation_fit: "applicable",
            automation_rationale: "Stable path",
            availability: "available",
            preconditions: "",
            steps: ["Login"],
            expected_result: "Home loads",
            gherkin: "",
            user_edited: false,
          },
          {
            candidate_id: "manual-1",
            test_type: "manual",
            automation_fit: "unclear",
            automation_rationale: "Ticket lacks harness detail",
            availability: "insufficient_evidence",
            preconditions: "",
            steps: [],
            expected_result: "",
            gherkin: "",
            user_edited: false,
          },
        ],
      });

    it("lets the user write steps manually and saves them as an available case", async () => {
      const user = userEvent.setup();
      const editingDraft = needsDetailDraft();
      vi.mocked(getTestDesignDraft).mockResolvedValue(editingDraft);
      vi.mocked(patchTestDesignDraft).mockImplementation(async ({ body }) => ({
        ...editingDraft,
        version: editingDraft.version + 1,
        generated_cases: body.generated_cases ?? editingDraft.generated_cases,
      }));

      render(<TestDesignWorkspace apiBaseUrl="http://api.test" draftId="draft-1" />);
      const clarification = await screen.findByRole("region", {
        name: /needs more detail from the ticket/i,
      });
      await user.click(
        within(clarification).getByRole("button", { name: /write steps manually/i }),
      );

      expect(
        screen.queryByRole("region", { name: /needs more detail from the ticket/i }),
      ).not.toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: /^back$/i }));
      expect(
        await screen.findByText(/each manual case needs at least one step/i),
      ).toBeInTheDocument();
      expect(patchTestDesignDraft).not.toHaveBeenCalled();

      const stepInputs = screen.getAllByLabelText(/^step 1$/i);
      await user.type(stepInputs[stepInputs.length - 1], "Run the harness");
      const expectedInputs = screen.getAllByLabelText(/^expected result 1$/i);
      await user.type(expectedInputs[expectedInputs.length - 1], "Harness passes");
      await user.click(screen.getByRole("button", { name: /^back$/i }));

      await waitFor(() => {
        expect(patchTestDesignDraft).toHaveBeenCalledWith(
          expect.objectContaining({
            body: expect.objectContaining({
              generated_cases: expect.arrayContaining([
                expect.objectContaining({
                  candidate_id: "manual-1",
                  availability: "available",
                  steps: ["Run the harness"],
                  expected_result: "Harness passes",
                }),
              ]),
            }),
          }),
        );
      });
    });

    it("removes a test from selection without touching other cases", async () => {
      const user = userEvent.setup();
      const editingDraft = needsDetailDraft();
      vi.mocked(getTestDesignDraft).mockResolvedValue(editingDraft);
      vi.mocked(patchTestDesignDraft).mockImplementation(async ({ body }) => ({
        ...editingDraft,
        version: editingDraft.version + 1,
        candidates: body.candidates ?? editingDraft.candidates,
        selected_candidate_ids: ["cand-positive"],
        generated_cases: editingDraft.generated_cases?.slice(0, 1) ?? [],
      }));

      render(<TestDesignWorkspace apiBaseUrl="http://api.test" draftId="draft-1" />);
      const clarification = await screen.findByRole("region", {
        name: /needs more detail from the ticket/i,
      });
      await user.click(
        within(clarification).getByRole("button", { name: /remove from selection/i }),
      );

      await waitFor(() => {
        expect(patchTestDesignDraft).toHaveBeenCalledWith(
          expect.objectContaining({
            body: expect.objectContaining({
              expected_version: editingDraft.version,
              candidates: expect.arrayContaining([
                expect.objectContaining({ candidate_id: "manual-1", selected: false }),
                expect.objectContaining({ candidate_id: "cand-positive", selected: true }),
              ]),
            }),
          }),
        );
      });
      expect(
        screen.queryByRole("region", { name: /needs more detail from the ticket/i }),
      ).not.toBeInTheDocument();
      expect(screen.getByRole("region", { name: /manual package/i })).toBeInTheDocument();
    });

    it("regenerates only that test from the updated ticket", async () => {
      const user = userEvent.setup();
      const editingDraft = needsDetailDraft();
      vi.mocked(getTestDesignDraft).mockResolvedValue(editingDraft);
      vi.mocked(generateTestDesignCases).mockResolvedValue(editingDraft);

      render(<TestDesignWorkspace apiBaseUrl="http://api.test" draftId="draft-1" />);
      const clarification = await screen.findByRole("region", {
        name: /needs more detail from the ticket/i,
      });
      await user.click(
        within(clarification).getByRole("button", { name: /^regenerate$/i }),
      );

      await waitFor(() => {
        expect(generateTestDesignCases).toHaveBeenCalledWith(
          expect.objectContaining({
            body: expect.objectContaining({
              overwrite_edited: true,
              candidate_ids: ["manual-1"],
            }),
          }),
        );
      });
    });
  });

  describe("auto-save", () => {
    it("saves a removed background and reordered steps without any button", async () => {
      const user = userEvent.setup();
      const initial = stepsDraft({
        cucumber_feature: "Login",
        cucumber_background: "Given the app is open",
        candidates: [
          candidate(),
          candidate({ candidate_id: "cand-cuke", title: "Cucumber path" }),
        ],
        selected_candidate_ids: ["cand-positive", "cand-cuke"],
        generated_cases: [
          {
            ...stepsDraft().generated_cases![0],
            steps: ["Login", "Open settings"],
          },
          {
            candidate_id: "cand-cuke",
            test_type: "cucumber",
            automation_fit: "applicable",
            automation_rationale: "Stable",
            availability: "available",
            preconditions: "",
            steps: [],
            expected_result: "",
            gherkin: "Given logged out",
            user_edited: false,
          },
        ],
      });
      vi.mocked(getTestDesignDraft).mockResolvedValue(initial);
      vi.mocked(patchTestDesignDraft).mockImplementation(async ({ body }) => ({
        ...initial,
        version: initial.version + 1,
        cucumber_background: body.cucumber_background ?? initial.cucumber_background,
        generated_cases: body.generated_cases ?? initial.generated_cases,
      }));

      render(<TestDesignWorkspace apiBaseUrl="http://api.test" draftId="draft-1" />);
      await user.click(await screen.findByRole("button", { name: /remove background/i }));
      screen.getByRole("button", { name: /reorder step 2/i }).focus();
      await user.keyboard("{ArrowUp}");
      expect(screen.getByText(/^unsaved changes$/i)).toBeInTheDocument();

      await waitFor(
        () => {
          expect(patchTestDesignDraft).toHaveBeenCalledWith(
            expect.objectContaining({
              body: expect.objectContaining({
                cucumber_background: "",
                generated_cases: expect.arrayContaining([
                  expect.objectContaining({ steps: ["Open settings", "Login"] }),
                ]),
              }),
            }),
          );
        },
        { timeout: 2000 },
      );
      expect(patchTestDesignDraft).toHaveBeenCalledTimes(1);
      expect(await screen.findByText(/^saved$/i)).toBeInTheDocument();
    });

    it("saves a renamed scenario together with step edits", async () => {
      const user = userEvent.setup();
      const initial = stepsDraft({
        candidates: [candidate({ candidate_id: "cand-cuke", title: "Cucumber path" })],
        selected_candidate_ids: ["cand-cuke"],
        generated_cases: [
          {
            candidate_id: "cand-cuke",
            test_type: "cucumber",
            automation_fit: "applicable",
            automation_rationale: "Stable",
            availability: "available",
            preconditions: "",
            steps: [],
            expected_result: "",
            gherkin: "Given logged out",
            user_edited: false,
          },
        ],
      });
      vi.mocked(getTestDesignDraft).mockResolvedValue(initial);
      vi.mocked(patchTestDesignDraft).mockImplementation(async ({ body }) => ({
        ...initial,
        version: initial.version + 1,
        candidates: body.candidates ?? initial.candidates,
        generated_cases: body.generated_cases ?? initial.generated_cases,
      }));

      render(<TestDesignWorkspace apiBaseUrl="http://api.test" draftId="draft-1" />);
      const name = await screen.findByLabelText(/^scenario name$/i);
      await user.clear(name);
      await user.type(name, "Guest login");
      await user.type(screen.getByLabelText(/scenario steps for/i), "\nThen home");

      await waitFor(
        () => {
          expect(patchTestDesignDraft).toHaveBeenCalledWith(
            expect.objectContaining({
              body: expect.objectContaining({
                candidates: [
                  expect.objectContaining({
                    candidate_id: "cand-cuke",
                    title: "Guest login",
                  }),
                ],
                generated_cases: [
                  expect.objectContaining({
                    gherkin: "Given logged out\nThen home",
                  }),
                ],
              }),
            }),
          );
        },
        { timeout: 2000 },
      );
      expect(patchTestDesignDraft).toHaveBeenCalledTimes(1);
      expect(await screen.findByText(/^saved$/i)).toBeInTheDocument();
      expect(screen.getByDisplayValue("Guest login")).toBeInTheDocument();
    });

    it("saves test selection changes automatically", async () => {
      const user = userEvent.setup();
      await renderWorkspace();

      await user.click(screen.getByRole("checkbox", { name: /keep manual edge case/i }));

      await waitFor(
        () => {
          expect(patchTestDesignDraft).toHaveBeenCalledWith(
            expect.objectContaining({
              body: expect.objectContaining({
                expected_version: 3,
                candidates: expect.arrayContaining([
                  expect.objectContaining({ candidate_id: "manual-1", selected: false }),
                ]),
              }),
            }),
          );
        },
        { timeout: 2000 },
      );
    });

    it("warns before leaving while edits cannot be saved yet", async () => {
      const user = userEvent.setup();
      await renderStepsWorkspace();

      await user.clear(screen.getByLabelText(/^step 1$/i));
      const event = new Event("beforeunload", { cancelable: true });
      window.dispatchEvent(event);
      expect(event.defaultPrevented).toBe(true);

      await new Promise((resolve) => setTimeout(resolve, 1000));
      expect(patchTestDesignDraft).not.toHaveBeenCalled();
      expect(screen.getByText(/^unsaved changes$/i)).toBeInTheDocument();
    });
  });

  describe("moving between test selection and test steps", () => {
    const positiveCase = {
      candidate_id: "cand-positive",
      test_type: "manual" as const,
      automation_fit: "applicable" as const,
      automation_rationale: "Stable path",
      availability: "available" as const,
      preconditions: "Logged out",
      steps: ["Login"],
      expected_result: "Home",
      gherkin: "",
      user_edited: true,
    };
    const manualCase = {
      ...positiveCase,
      candidate_id: "manual-1",
      steps: ["Open edge"],
      user_edited: false,
    };
    const editingDraft = () =>
      draft({
        status: "case_editing",
        evidence_fingerprint: "fp-1",
        candidates: [
          candidate(),
          candidate({
            candidate_id: "manual-1",
            title: "Manual edge case",
            category: "edge_case",
            origin: "manual",
            selected: false,
          }),
        ],
        selected_candidate_ids: ["cand-positive"],
        generated_cases: [positiveCase],
      });

    it("goes back to test selection and forward again without regenerating", async () => {
      const user = userEvent.setup();
      vi.mocked(getTestDesignDraft).mockResolvedValue(editingDraft());

      render(<TestDesignWorkspace apiBaseUrl="http://api.test" draftId="draft-1" />);
      await screen.findByRole("region", { name: /manual package/i });

      await user.click(screen.getByRole("button", { name: /^back$/i }));
      expect(await screen.findByDisplayValue("Covers happy path")).toBeInTheDocument();
      expect(screen.getByText(/existing test steps are kept/i)).toBeInTheDocument();

      const progress = screen.getByRole("navigation", { name: /workflow progress/i });
      await user.click(within(progress).getByRole("button", { name: /test steps/i }));
      expect(await screen.findByRole("region", { name: /manual package/i })).toBeInTheDocument();
      expect(screen.getByLabelText(/^step 1$/i)).toHaveValue("Login");

      await user.click(within(progress).getByRole("button", { name: /test selection/i }));
      await user.click(await screen.findByRole("button", { name: /^next$/i }));
      expect(await screen.findByRole("region", { name: /manual package/i })).toBeInTheDocument();

      expect(generateTestDesignCases).not.toHaveBeenCalled();
      expect(patchTestDesignDraft).not.toHaveBeenCalled();
      expect(confirmTestDesignDraft).not.toHaveBeenCalled();
    });

    it("generates steps only for newly selected tests and keeps existing steps", async () => {
      const user = userEvent.setup();
      const initial = editingDraft();
      const reselected = {
        ...initial,
        candidates: initial.candidates.map((item) => ({ ...item, selected: true })),
        selected_candidate_ids: ["cand-positive", "manual-1"],
      };
      vi.mocked(getTestDesignDraft).mockResolvedValue(initial);
      vi.mocked(patchTestDesignDraft).mockResolvedValue({
        ...reselected,
        status: "coverage_review",
        evidence_fingerprint: null,
        version: 4,
      });
      vi.mocked(confirmTestDesignDraft).mockResolvedValue({
        ...reselected,
        version: 5,
      });
      vi.mocked(generateTestDesignCases).mockResolvedValue({
        ...reselected,
        version: 6,
        generated_cases: [positiveCase, manualCase],
      });

      render(<TestDesignWorkspace apiBaseUrl="http://api.test" draftId="draft-1" />);
      await screen.findByRole("region", { name: /manual package/i });
      await user.click(screen.getByRole("button", { name: /^back$/i }));
      await user.click(
        await screen.findByRole("checkbox", { name: /keep manual edge case/i }),
      );
      await user.click(screen.getByRole("button", { name: /^next$/i }));

      await waitFor(() => {
        expect(generateTestDesignCases).toHaveBeenCalledWith(
          expect.objectContaining({
            body: expect.objectContaining({
              candidate_ids: ["manual-1"],
              overwrite_edited: false,
            }),
          }),
        );
      });
      expect(confirmTestDesignDraft).toHaveBeenCalledWith(
        expect.objectContaining({ body: { expected_version: 4 } }),
      );
      expect(await screen.findByDisplayValue("Open edge")).toBeInTheDocument();
      expect(screen.getByDisplayValue("Login")).toBeInTheDocument();
      expect(screen.getByText(/other steps were kept/i)).toBeInTheDocument();
    });

    it("saves unsaved step edits before going back", async () => {
      const user = userEvent.setup();
      const initial = editingDraft();
      vi.mocked(getTestDesignDraft).mockResolvedValue(initial);
      vi.mocked(patchTestDesignDraft).mockImplementation(async ({ body }) => ({
        ...initial,
        version: initial.version + 1,
        generated_cases: body.generated_cases ?? initial.generated_cases,
      }));

      render(<TestDesignWorkspace apiBaseUrl="http://api.test" draftId="draft-1" />);
      await screen.findByRole("region", { name: /manual package/i });
      const step = screen.getByLabelText(/^step 1$/i);
      await user.clear(step);
      await user.type(step, "Sign in");
      await user.click(screen.getByRole("button", { name: /^back$/i }));

      await waitFor(() => {
        expect(patchTestDesignDraft).toHaveBeenCalledWith(
          expect.objectContaining({
            body: expect.objectContaining({
              generated_cases: [expect.objectContaining({ steps: ["Sign in"] })],
            }),
          }),
        );
      });
      expect(await screen.findByDisplayValue("Covers happy path")).toBeInTheDocument();
    });
  });
});
