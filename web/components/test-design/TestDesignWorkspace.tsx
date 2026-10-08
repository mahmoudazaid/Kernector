"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Loader } from "@/components/ui/Loader";
import { LoadingState } from "@/components/states/LoadingState";
import { NumberedListEditor } from "@/components/test-design/NumberedListEditor";
import { UnavailableState } from "@/components/states/UnavailableState";
import {
  confirmTestDesignDraft,
  exportTestDesignGoogleDrive,
  exportTestDesignXray,
  generateTestDesignCases,
  getTestDesignDraft,
  getTestDesignXrayStatus,
  patchTestDesignDraft,
  type ExportTestDesignXrayResponse,
  type PatchTestDesignDraftRequest,
  type TestCoverageDraftResponse,
  type TestDesignXrayStatusResponse,
} from "@/lib/api/test-design";
import { ApiError } from "@/lib/api/errors";
import { formatTimestamp } from "@/lib/format/timestamp";
import { GoogleDrivePicker } from "@/components/documents/GoogleDrivePicker";
import { recordTestDesignCoverageConfirmed } from "@/lib/session/conversations";
import { useRuntimeCatalog } from "@/lib/settings/use-runtime-catalog";

const PACK_ID = "software-delivery";

const CATEGORY_ORDER = [
  "positive",
  "negative",
  "edge_case",
] as const;

type Props = {
  apiBaseUrl: string;
  draftId: string;
};

type DraftCandidate = TestCoverageDraftResponse["candidates"][number];
type DraftGeneratedCase = NonNullable<
  TestCoverageDraftResponse["generated_cases"]
>[number];

function formatCategory(value: string): string {
  return value.replaceAll("_", " ");
}

function formatStatus(value: string): string {
  return value.replaceAll("_", " ");
}

function splitStoredLines(
  value: string,
  options: { allowEmpty: boolean },
): string[] {
  // Empty string = no rows when allowEmpty; otherwise keep one blank row.
  // Single space = one blank row being edited.
  if (value === "") {
    return options.allowEmpty ? [] : [""];
  }
  if (value === " ") {
    return [""];
  }
  if (value.includes("\n")) {
    return value.split("\n").map(stripListPrefix);
  }
  if (value.includes("; ")) {
    return value
      .split("; ")
      .map((line) => stripListPrefix(line.trim()))
      .filter((line) => line.length > 0);
  }
  return [stripListPrefix(value)];
}

const LIST_PREFIX = /^\s*(?:\d+[.)]\s+|[-*•]\s+)/;

function stripListPrefix(value: string): string {
  let previous = value;
  for (;;) {
    const next = previous.replace(LIST_PREFIX, "");
    if (next === previous) {
      return previous.trimStart();
    }
    previous = next;
  }
}

function splitPreconditionLines(value: string): string[] {
  return splitStoredLines(value, { allowEmpty: true });
}

function joinPreconditionLines(lines: readonly string[]): string {
  return joinStoredLines(lines);
}

function persistPreconditions(value: string): string {
  return persistStoredLines(value);
}

function normalizeStepLines(steps: readonly string[] | undefined): string[] {
  if (!steps || steps.length === 0) {
    return [""];
  }
  return steps.map((step) => stripListPrefix(step));
}

function persistStepLines(steps: readonly string[]): string[] {
  return steps
    .map((step) => stripListPrefix(step.trim()).trim())
    .filter((step) => step.length > 0);
}

function splitExpectedLines(value: string): string[] {
  return splitStoredLines(value, { allowEmpty: true }).map(stripListPrefix);
}

function normalizeExpectedLines(value: string): string[] {
  const lines = splitExpectedLines(value);
  return lines.length > 0 ? lines : [""];
}

function joinExpectedLines(lines: readonly string[]): string {
  return joinStoredLines(lines);
}

function persistExpectedResult(value: string): string {
  return persistStoredLines(value);
}

function joinStoredLines(lines: readonly string[]): string {
  if (lines.length === 0) {
    return "";
  }
  if (lines.length === 1 && lines[0] === "") {
    return " ";
  }
  return lines.join("\n");
}

function persistStoredLines(value: string): string {
  return joinStoredLines(
    splitStoredLines(value, { allowEmpty: true })
      .map((line) => line.trim())
      .filter((line) => line.length > 0),
  );
}

const MAX_CANDIDATES = 40;
const MAX_TITLE_CHARS = 200;
const MAX_CASE_LINES = 40;

type WorkspaceStep = "coverage" | "cases";

const WORKSPACE_STEPS: { id: WorkspaceStep; label: string }[] = [
  { id: "coverage", label: "Test selection" },
  { id: "cases", label: "Test steps" },
];

function workspaceStep(draft: TestCoverageDraftResponse): WorkspaceStep {
  if (draft.status === "case_editing" && (draft.generated_cases?.length ?? 0) > 0) {
    return "cases";
  }
  return "coverage";
}

function missingCaseIds(draft: TestCoverageDraftResponse): string[] {
  const withCases = new Set(
    (draft.generated_cases ?? []).map((item) => item.candidate_id),
  );
  return draft.candidates
    .filter((candidate) => candidate.selected && !withCases.has(candidate.candidate_id))
    .map((candidate) => candidate.candidate_id);
}

const AUTOSAVE_DELAY_MS = 800;

function buildCasesPatch(
  draft: TestCoverageDraftResponse,
): { error: string } | { body: PatchTestDesignDraftRequest } {
  const cases = draft.generated_cases ?? [];
  const availableManual = cases.filter(
    (item) => item.availability === "available" && item.test_type === "manual",
  );
  if (availableManual.some((item) => persistStepLines(item.steps ?? []).length === 0)) {
    return { error: "Each manual case needs at least one step." };
  }
  if (
    availableManual.some(
      (item) => persistExpectedResult(item.expected_result ?? "").trim().length === 0,
    )
  ) {
    return { error: "Each manual case needs at least one expected result." };
  }
  if (
    cases.some(
      (item) =>
        item.availability === "available" &&
        item.test_type === "cucumber" &&
        !item.gherkin.trim(),
    )
  ) {
    return { error: "Each Cucumber test needs at least one step." };
  }
  return {
    body: {
      expected_version: draft.version,
      cucumber_feature: draft.cucumber_feature ?? "",
      cucumber_background: draft.cucumber_background ?? "",
      generated_cases: cases.map((item) =>
        item.test_type === "manual" && item.availability === "available"
          ? {
              ...item,
              preconditions: persistPreconditions(item.preconditions),
              steps: persistStepLines(item.steps ?? []),
              expected_result: persistExpectedResult(item.expected_result ?? ""),
            }
          : {
              ...item,
              preconditions: persistPreconditions(item.preconditions),
              steps: [],
              expected_result: "",
            },
      ),
    },
  };
}

function groupCandidatesByCategory(
  candidates: readonly DraftCandidate[],
): { category: string; candidates: DraftCandidate[] }[] {
  const byCategory = new Map<string, DraftCandidate[]>();
  for (const candidate of candidates) {
    const list = byCategory.get(candidate.category) ?? [];
    list.push(candidate);
    byCategory.set(candidate.category, list);
  }
  const ordered: { category: string; candidates: DraftCandidate[] }[] = [];
  for (const category of CATEGORY_ORDER) {
    ordered.push({
      category,
      candidates: byCategory.get(category) ?? [],
    });
    byCategory.delete(category);
  }
  for (const [category, group] of byCategory) {
    ordered.push({ category, candidates: group });
  }
  return ordered;
}

function newManualCandidateId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `manual-${crypto.randomUUID()}`;
  }
  return `manual-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

const XRAY_KEYS_SHOWN = 5;

function xrayConfirmText(
  status: TestDesignXrayStatusResponse | null,
  count: number,
): string {
  const tests = `${count} test${count === 1 ? "" : "s"}`;
  const target = status?.link_issue_key
    ? ` linked to ${status.link_issue_key}`
    : "";
  const create = `Create ${tests} in ${status?.project_key ?? "Xray"}${target}. Every run creates new tests.`;
  const keys = status?.created_keys ?? [];
  if (keys.length === 0) {
    return create;
  }
  const shown = keys.slice(0, XRAY_KEYS_SHOWN).join(", ");
  const more =
    keys.length > XRAY_KEYS_SHOWN
      ? ` and ${keys.length - XRAY_KEYS_SHOWN} more`
      : "";
  const when = status?.last_created_at
    ? ` on ${formatTimestamp(status.last_created_at)}`
    : "";
  return `Already created ${shown}${more}${when}. ${create}`;
}

export function TestDesignWorkspace({ apiBaseUrl, draftId }: Props) {
  const router = useRouter();
  const {
    catalog,
    error: catalogError,
    loading: catalogLoading,
    reload: reloadCatalog,
  } = useRuntimeCatalog(apiBaseUrl);
  const packEnabled = catalog?.enabled_packs.includes(PACK_ID) ?? false;
  const [draft, setDraft] = useState<TestCoverageDraftResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [saveNote, setSaveNote] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [casesDirty, setCasesDirty] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [autoExportArmed, setAutoExportArmed] = useState(false);
  const [backgroundOpen, setBackgroundOpen] = useState(false);
  const [viewStep, setViewStep] = useState<WorkspaceStep | null>(null);
  const [exitOpen, setExitOpen] = useState(false);
  const [autosaving, setAutosaving] = useState(false);
  const [xrayStatus, setXrayStatus] =
    useState<TestDesignXrayStatusResponse | null>(null);
  const [xrayOpen, setXrayOpen] = useState(false);
  const [xrayReceipt, setXrayReceipt] =
    useState<ExportTestDesignXrayResponse | null>(null);
  const editRevision = useRef(0);
  const failedRevision = useRef(-1);
  const hasUnsaved = dirty || casesDirty || autosaving;

  useEffect(() => {
    if (!draft || busy || autosaving || (!dirty && !casesDirty)) {
      return;
    }
    if (failedRevision.current === editRevision.current) {
      return;
    }
    const timer = window.setTimeout(() => void autosave(), AUTOSAVE_DELAY_MS);
    return () => window.clearTimeout(timer);
    // autosave closes over the latest draft; each edit reschedules it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft, dirty, casesDirty, busy, autosaving]);

  useEffect(() => {
    if (!hasUnsaved) {
      return;
    }
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [hasUnsaved]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const params = new URLSearchParams(window.location.search);
    if (params.get("export") === "1") {
      setAutoExportArmed(true);
    }
  }, []);

  useEffect(() => {
    if (!packEnabled) {
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const loaded = await getTestDesignDraft({
          baseUrl: apiBaseUrl,
          draftId,
        });
        if (!cancelled) {
          setDraft(loaded);
          setError(null);
          setDirty(false);
        }
      } catch (caught) {
        if (!cancelled) {
          if (caught instanceof ApiError && caught.status === 404) {
            setError(caught.detail);
          } else {
            setError("Could not load this draft.");
          }
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [apiBaseUrl, draftId, packEnabled]);

  useEffect(() => {
    if (!packEnabled) {
      return;
    }
    let cancelled = false;
    getTestDesignXrayStatus({ baseUrl: apiBaseUrl, draftId })
      .then((status) => {
        if (!cancelled) {
          setXrayStatus(status);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setXrayStatus(null);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [apiBaseUrl, draftId, packEnabled]);

  useEffect(() => {
    if (!autoExportArmed || !draft || busy || exportOpen) {
      return;
    }
    setAutoExportArmed(false);
    void openExportDialog();
    router.replace(`/test-design/${encodeURIComponent(draftId)}`);
    // One-shot arming from ?export=1; openExportDialog closes over latest draft.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoExportArmed, draft, busy, exportOpen, draftId, router]);

  if (catalogLoading && !catalog) {
    return (
      <section className="kern-test-design" aria-busy="true">
        <header className="kern-hub-head">
          <h1>Test Design</h1>
        </header>
        <div className="kern-content-state">
          <LoadingState label="Loading Test Design" />
        </div>
      </section>
    );
  }

  if (catalogError) {
    return (
      <section className="kern-test-design">
        <header className="kern-hub-head">
          <h1>Test Design</h1>
        </header>
        <div className="kern-content-state">
          <UnavailableState
            title="Test Design unavailable"
            description={catalogError}
          >
            <Button
              type="button"
              variant="secondary"
              disabled={catalogLoading}
              onClick={reloadCatalog}
            >
              {catalogLoading ? "Checking..." : "Retry"}
            </Button>
          </UnavailableState>
        </div>
      </section>
    );
  }

  if (catalog && !packEnabled) {
    return (
      <section className="kern-test-design">
        <header className="kern-hub-head">
          <h1>Test Design</h1>
        </header>
        <div className="kern-content-state">
          <UnavailableState
            title="Test Design unavailable"
            description="Enable the Software Delivery pack to use Test Design."
          />
        </div>
      </section>
    );
  }

  if (!catalog) {
    return (
      <section className="kern-test-design" aria-busy="true">
        <header className="kern-hub-head">
          <h1>Test Design</h1>
        </header>
        <div className="kern-content-state">
          <LoadingState label="Loading Test Design" />
        </div>
      </section>
    );
  }

  if (error && !draft) {
    return (
      <section className="kern-test-design">
        <header className="kern-hub-head">
          <h1>Test Design</h1>
        </header>
        <div className="kern-content-state">
          <UnavailableState title="Draft unavailable" description={error} />
        </div>
      </section>
    );
  }

  if (!draft) {
    return (
      <section className="kern-test-design" aria-busy="true">
        <header className="kern-hub-head">
          <h1>Test Design</h1>
        </header>
        <div className="kern-content-state">
          <LoadingState label="Loading draft" />
        </div>
      </section>
    );
  }

  async function saveDraft(): Promise<boolean> {
    if (!draft) {
      return false;
    }
    const blankTitle = draft.candidates.find(
      (candidate) => !candidate.title.trim(),
    );
    if (blankTitle) {
      setError("Every candidate needs a title before saving.");
      setSaveNote(null);
      return false;
    }
    setBusy(true);
    setError(null);
    setSaveNote(null);
    try {
      const saved = await patchTestDesignDraft({
        baseUrl: apiBaseUrl,
        draftId: draft.draft_id,
        body: {
          expected_version: draft.version,
          candidates: draft.candidates,
        },
      });
      setDraft(saved);
      setSaveNote("Draft saved.");
      setDirty(false);
      setCasesDirty(false);
      return true;
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409) {
        setError(
          "This draft changed elsewhere. Your unsaved edits are still on screen — reload to discard them, or save again after refreshing.",
        );
      } else {
        setError("Could not save draft.");
      }
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function openExportDialog() {
    if (!draft || selectedCount === 0 || busy) {
      return;
    }
    setError(null);
    if (casesDirty) {
      if (!(await saveCases())) {
        return;
      }
    } else if (dirty) {
      const saved = await saveDraft();
      if (!saved) {
        return;
      }
    }
    setExportOpen(true);
  }

  async function autosave() {
    if (!draft) {
      return;
    }
    const revision = editRevision.current;
    const savingCoverage =
      dirty && draft.candidates.every((candidate) => candidate.title.trim());
    const casesPatch = casesDirty ? buildCasesPatch(draft) : null;
    const savingCases = casesPatch !== null && !("error" in casesPatch);
    if (!savingCoverage && !savingCases) {
      return;
    }
    const body: PatchTestDesignDraftRequest = {
      ...(casesPatch && "body" in casesPatch
        ? casesPatch.body
        : { expected_version: draft.version }),
      ...(savingCoverage ? { candidates: draft.candidates } : {}),
    };
    setAutosaving(true);
    try {
      const saved = await patchTestDesignDraft({
        baseUrl: apiBaseUrl,
        draftId: draft.draft_id,
        body,
      });
      const unchangedSinceSend = editRevision.current === revision;
      if (unchangedSinceSend) {
        if (savingCoverage) {
          setDirty(false);
        }
        if (savingCases) {
          setCasesDirty(false);
        }
      }
      if (unchangedSinceSend && !casesDirty) {
        setDraft(saved);
      } else {
        setDraft((current) =>
          current
            ? {
                ...current,
                version: saved.version,
                status: saved.status,
                evidence_fingerprint: saved.evidence_fingerprint,
              }
            : current,
        );
      }
    } catch (caught) {
      failedRevision.current = revision;
      setError(
        caught instanceof ApiError && caught.status === 409
          ? "This draft changed elsewhere. Your edits are still on screen — reload to see the latest version."
          : "Could not auto-save your changes. They'll be saved on your next edit, Next, Back, or Export.",
      );
    } finally {
      setAutosaving(false);
    }
  }

  function markDirty() {
    editRevision.current += 1;
    setSaveNote(null);
    setError(null);
    setDirty(true);
  }

  function toggleCandidate(candidateId: string) {
    markDirty();
    setDraft((current) => {
      if (!current) {
        return current;
      }
      const candidates = current.candidates.map((candidate) =>
        candidate.candidate_id === candidateId
          ? { ...candidate, selected: !candidate.selected }
          : candidate,
      );
      return {
        ...current,
        candidates,
        selected_candidate_ids: candidates
          .filter((candidate) => candidate.selected)
          .map((candidate) => candidate.candidate_id),
      };
    });
  }

  function updateCandidateTitle(candidateId: string, title: string) {
    markDirty();
    setDraft((current) => {
      if (!current) {
        return current;
      }
      return {
        ...current,
        candidates: current.candidates.map((candidate) =>
          candidate.candidate_id === candidateId
            ? { ...candidate, title: title.slice(0, MAX_TITLE_CHARS) }
            : candidate,
        ),
      };
    });
  }

  function updateCandidateTestType(
    candidateId: string,
    testType: "manual" | "cucumber" | null,
  ) {
    markDirty();
    setDraft((current) => {
      if (!current) {
        return current;
      }
      const generated_cases = (current.generated_cases ?? []).filter(
        (item) => item.candidate_id !== candidateId,
      );
      return {
        ...current,
        candidates: current.candidates.map((candidate) =>
          candidate.candidate_id === candidateId
            ? { ...candidate, test_type: testType }
            : candidate,
        ),
        generated_cases,
      };
    });
  }

  function updateGeneratedCase(
    candidateId: string,
    patch: Partial<DraftGeneratedCase>,
  ) {
    editRevision.current += 1;
    setCasesDirty(true);
    setSaveNote(null);
    setError(null);
    setDraft((current) => {
      if (!current) {
        return current;
      }
      return {
        ...current,
        generated_cases: (current.generated_cases ?? []).map((item) =>
          item.candidate_id === candidateId ? { ...item, ...patch } : item,
        ),
      };
    });
  }

  function writeCaseManually(candidateId: string) {
    const item = draft?.generated_cases?.find(
      (entry) => entry.candidate_id === candidateId,
    );
    if (!item) {
      return;
    }
    updateGeneratedCase(
      candidateId,
      item.test_type === "cucumber"
        ? {
            availability: "available",
            preconditions: "",
            steps: [],
            expected_result: "",
            gherkin: "Given ",
          }
        : {
            availability: "available",
            preconditions: "",
            steps: [""],
            expected_result: "",
            gherkin: "",
          },
    );
    setSaveNote(
      "Write the steps. Changes save automatically.",
    );
  }

  async function removeFromSelection(candidateId: string) {
    if (!draft || busy) {
      return;
    }
    const working = casesDirty ? await saveCases() : draft;
    if (!working) {
      return;
    }
    setBusy(true);
    setError(null);
    setSaveNote(null);
    try {
      const saved = await patchTestDesignDraft({
        baseUrl: apiBaseUrl,
        draftId: working.draft_id,
        body: {
          expected_version: working.version,
          candidates: working.candidates.map((candidate) =>
            candidate.candidate_id === candidateId
              ? { ...candidate, selected: false }
              : candidate,
          ),
        },
      });
      setDraft(saved);
      setDirty(false);
      setSaveNote("Test removed from selection.");
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409) {
        setError("This draft changed elsewhere. Reload before removing tests.");
      } else {
        setError("Could not remove the test.");
      }
    } finally {
      setBusy(false);
    }
  }

  function updateCucumberShared(
    patch: Partial<
      Pick<TestCoverageDraftResponse, "cucumber_feature" | "cucumber_background">
    >,
  ) {
    editRevision.current += 1;
    setCasesDirty(true);
    setSaveNote(null);
    setError(null);
    setDraft((current) => {
      if (!current) {
        return current;
      }
      return { ...current, ...patch };
    });
  }

  async function saveCases(): Promise<TestCoverageDraftResponse | null> {
    if (!draft) {
      return null;
    }
    const patch = buildCasesPatch(draft);
    if ("error" in patch) {
      setError(patch.error);
      setSaveNote(null);
      return null;
    }
    setBusy(true);
    setError(null);
    setSaveNote(null);
    try {
      const saved = await patchTestDesignDraft({
        baseUrl: apiBaseUrl,
        draftId: draft.draft_id,
        body: patch.body,
      });
      setDraft(saved);
      setCasesDirty(false);
      setSaveNote("Test steps saved.");
      return saved;
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409) {
        setError(
          "This draft changed elsewhere. Your unsaved edits are still on screen — reload to discard them, or save again after refreshing.",
        );
      } else {
        setError("Could not save test steps.");
      }
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function runGenerate(
    current: TestCoverageDraftResponse,
    candidateIds?: string[],
    overwriteEdited = false,
  ): Promise<void> {
    if (current.status !== "ready" && current.status !== "case_editing") {
      return;
    }
    const generated = await generateTestDesignCases({
      baseUrl: apiBaseUrl,
      draftId: current.draft_id,
      body: {
        expected_version: current.version,
        overwrite_edited: overwriteEdited,
        ...(candidateIds ? { candidate_ids: candidateIds } : {}),
        type_overrides: current.candidates
          .filter((candidate) => candidate.selected && candidate.test_type)
          .map((candidate) => ({
            candidate_id: candidate.candidate_id,
            test_type: candidate.test_type as string,
          })),
      },
    });
    setDraft(generated);
    setDirty(false);
    setCasesDirty(false);
    setSaveNote(
      candidateIds
        ? `Generated steps for ${candidateIds.length} test(s). Other steps were kept.`
        : "Generated test steps with expected results.",
    );
  }

  async function regenerateCase(candidateId: string) {
    if (!draft || busy) {
      return;
    }
    const working = casesDirty ? await saveCases() : draft;
    if (!working) {
      return;
    }
    setBusy(true);
    setError(null);
    setSaveNote(null);
    try {
      await runGenerate(working, [candidateId], true);
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409) {
        if (caught.code === "test_design_evidence_changed") {
          setError(caught.detail);
        } else {
          setError(
            "This draft changed elsewhere. Reload before generating again.",
          );
        }
      } else {
        setError("Could not generate detailed cases.");
      }
    } finally {
      setBusy(false);
    }
  }

  function addCandidate(category: string) {
    if (!draft || draft.candidates.length >= MAX_CANDIDATES) {
      return;
    }
    markDirty();
    const candidateId = newManualCandidateId();
    setDraft((current) => {
      if (!current) {
        return current;
      }
      const next: DraftCandidate = {
        candidate_id: candidateId,
        title: "",
        category,
        rationale: "Manually added",
        evidence_references: [],
        selected: true,
        origin: "manual",
      };
      const candidates = [...current.candidates, next];
      return {
        ...current,
        candidates,
        selected_candidate_ids: candidates
          .filter((candidate) => candidate.selected)
          .map((candidate) => candidate.candidate_id),
      };
    });
    queueMicrotask(() => {
      const input = document.getElementById(
        `candidate-title-${candidateId}`,
      ) as HTMLInputElement | null;
      input?.focus();
    });
  }

  function removeCandidate(candidateId: string) {
    markDirty();
    setDraft((current) => {
      if (!current) {
        return current;
      }
      const candidate = current.candidates.find(
        (item) => item.candidate_id === candidateId,
      );
      if (candidate?.origin !== "manual") {
        return current;
      }
      const candidates = current.candidates.filter(
        (item) => item.candidate_id !== candidateId,
      );
      return {
        ...current,
        candidates,
        selected_candidate_ids: candidates
          .filter((item) => item.selected)
          .map((item) => item.candidate_id),
      };
    });
  }

  async function goNext() {
    if (!draft || selectedCount === 0 || casesDirty || busy) {
      return;
    }
    if (!dirty && draft.status === "case_editing" && missingCaseIds(draft).length === 0) {
      setError(null);
      setViewStep("cases");
      return;
    }
    const blankTitle = draft.candidates.find(
      (candidate) => !candidate.title.trim(),
    );
    if (dirty && blankTitle) {
      setError("Every candidate needs a title before continuing.");
      return;
    }
    setBusy(true);
    setError(null);
    setSaveNote(null);
    try {
      let working = draft;
      if (dirty) {
        working = await patchTestDesignDraft({
          baseUrl: apiBaseUrl,
          draftId: working.draft_id,
          body: {
            expected_version: working.version,
            candidates: working.candidates,
          },
        });
        setDraft(working);
        setDirty(false);
      }
      if (working.status === "coverage_review") {
        working = await confirmTestDesignDraft({
          baseUrl: apiBaseUrl,
          draftId: working.draft_id,
          body: { expected_version: working.version },
        });
        recordTestDesignCoverageConfirmed({
          conversationId: working.conversation_id,
          draftId: working.draft_id,
          ticketIdentifier: working.ticket_identifier,
          selectedCount: working.selected_candidate_ids.length,
        });
        setDraft(working);
      }
      const missing = missingCaseIds(working);
      if (missing.length > 0) {
        const hasExisting = (working.generated_cases?.length ?? 0) > 0;
        await runGenerate(working, hasExisting ? missing : undefined);
      }
      setViewStep("cases");
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409) {
        if (caught.code === "test_design_evidence_changed") {
          setError(caught.detail);
        } else {
          setError(
            "This draft changed elsewhere. Your unsaved edits are still on screen — reload to discard them, or refresh before continuing.",
          );
        }
      } else {
        setError("Could not generate detailed cases.");
      }
    } finally {
      setBusy(false);
    }
  }

  async function goBackToCoverage() {
    if (busy) {
      return;
    }
    if (casesDirty && !(await saveCases())) {
      return;
    }
    setViewStep("coverage");
  }

  function requestExit() {
    if (busy) {
      return;
    }
    if (dirty || casesDirty) {
      setExitOpen(true);
      return;
    }
    router.push(chatHref);
  }

  async function saveAndExit() {
    setExitOpen(false);
    const saved = casesDirty ? Boolean(await saveCases()) : await saveDraft();
    if (saved) {
      router.push(chatHref);
    }
  }

  async function exportSelectedFolder(folderId: string, folderName: string) {
    if (!draft || selectedCount === 0) {
      return;
    }
    setBusy(true);
    setError(null);
    setSaveNote(null);
    try {
      const receipt = await exportTestDesignGoogleDrive({
        baseUrl: apiBaseUrl,
        draftId: draft.draft_id,
        body: { folder_id: folderId, destination_label: folderName },
      });
      setExportOpen(false);
      setSaveNote(
        `Exported ${receipt.file_name} to ${folderName}.`,
      );
    } catch (caught) {
      if (
        caught instanceof ApiError &&
        caught.code === "test_design_unavailable"
      ) {
        setError("Google Drive export is unavailable.");
      } else if (
        caught instanceof ApiError &&
        caught.code === "google_drive_not_connected"
      ) {
        setError("Google Drive is not connected.");
      } else if (
        caught instanceof ApiError &&
        caught.code === "google_drive_reauthorization_required"
      ) {
        setError("Google Drive authorization was revoked. Connect again.");
      } else if (caught instanceof ApiError && caught.status === 422) {
        setError(caught.detail);
      } else {
        setError("Could not export to Google Drive.");
      }
    } finally {
      setBusy(false);
    }
  }

  async function openXrayDialog() {
    if (!draft || xrayCount === 0 || busy) {
      return;
    }
    setError(null);
    if (casesDirty) {
      if (!(await saveCases())) {
        return;
      }
    } else if (dirty && !(await saveDraft())) {
      return;
    }
    setXrayOpen(true);
  }

  async function createInXray() {
    if (!draft) {
      return;
    }
    setBusy(true);
    setError(null);
    setSaveNote(null);
    setXrayReceipt(null);
    try {
      const receipt = await exportTestDesignXray({
        baseUrl: apiBaseUrl,
        draftId: draft.draft_id,
        body: { expected_version: draft.version, link_source_issue: true },
      });
      setXrayOpen(false);
      setXrayReceipt(receipt);
      setXrayStatus((current) =>
        current
          ? {
              ...current,
              created_keys: [
                ...new Set([...current.created_keys, ...receipt.created_keys]),
              ],
              last_created_at: new Date().toISOString(),
            }
          : current,
      );
    } catch (caught) {
      setXrayOpen(false);
      if (caught instanceof ApiError && caught.code === "test_design_unavailable") {
        setError("Xray export is unavailable.");
      } else if (caught instanceof ApiError && caught.status === 409) {
        setError("This draft changed elsewhere. Reload it before creating Xray tests.");
      } else if (
        caught instanceof ApiError &&
        (caught.status === 422 || caught.status === 502)
      ) {
        setError(caught.detail);
      } else {
        setError("Could not create tests in Xray.");
      }
    } finally {
      setBusy(false);
    }
  }

  const selectedCount = draft.candidates.filter((c) => c.selected).length;
  const generatedCases = draft.generated_cases ?? [];
  const hasSteps = draft.status === "case_editing" && generatedCases.length > 0;
  const step: WorkspaceStep =
    viewStep === "cases" && !hasSteps
      ? "coverage"
      : (viewStep ?? workspaceStep(draft));
  const actionsLocked = busy || autosaving;
  const canNext = selectedCount > 0 && !actionsLocked && !casesDirty;
  const canRegenerate =
    (draft.status === "ready" || draft.status === "case_editing") && !actionsLocked;
  const canExport = selectedCount > 0 && !actionsLocked;
  const selectedIds = new Set(
    draft.candidates.filter((c) => c.selected).map((c) => c.candidate_id),
  );
  const xrayCount = generatedCases.filter(
    (item) =>
      item.availability === "available" && selectedIds.has(item.candidate_id),
  ).length;
  const canCreateInXray = xrayCount > 0 && !actionsLocked;
  const chatHref = `/chat/${encodeURIComponent(draft.conversation_id)}`;
  const cucumberCases = generatedCases.filter(
    (item) =>
      item.test_type === "cucumber" && item.availability === "available",
  );
  const manualCases = generatedCases.filter(
    (item) => item.test_type === "manual" && item.availability === "available",
  );
  const clarificationCases = generatedCases.filter(
    (item) => item.availability === "insufficient_evidence",
  );
  const hasCucumberCases = cucumberCases.length > 0;
  const showBackground =
    backgroundOpen || (draft.cucumber_background ?? "").trim().length > 0;
  const hasManualCases = manualCases.length > 0;
  const hasClarificationCases = clarificationCases.length > 0;
  const showTypeControls =
    draft.status === "coverage_review" ||
    draft.status === "ready" ||
    draft.status === "case_editing";
  const showCoveragePanel = step === "coverage";
  const showCasesPanel = step === "cases";
  const showNext = step === "coverage";

  const candidateTitleById = new Map(
    draft.candidates.map((candidate) => [candidate.candidate_id, candidate.title]),
  );

  const stepHint =
    step === "coverage"
      ? generatedCases.length > 0
        ? "Select, add, or remove tests, then Next. Existing test steps are kept; only new tests get generated steps."
        : "Select which tests to keep. Set Manual or Cucumber beside each title, then Next to generate test steps."
      : "Cucumber shares one Feature and Background; Manual uses Preconditions, Steps, and Expected Result. Tests that need more detail from the ticket stay out of export.";

  function stepAction(target: WorkspaceStep): (() => void) | null {
    if (target === step) {
      return null;
    }
    if (target === "coverage") {
      return actionsLocked ? null : () => void goBackToCoverage();
    }
    return generatedCases.length > 0 && canNext ? () => void goNext() : null;
  }

  return (
    <section className="kern-test-design" aria-busy={busy}>
      {busy ? (
        <div className="kern-test-design-busy" aria-hidden="true">
          <div className="kern-test-design-busy__mark">
            <Loader label="Working" size="md" />
          </div>
        </div>
      ) : null}

      <header className="kern-hub-head">
        <p className="kern-breadcrumb">
          <Link href={chatHref}>Chat</Link>
          <span aria-hidden="true">/</span>
          <strong>Test Design</strong>
        </p>
        <div className="kern-test-design-title-row">
          <div>
            <h1>Test Design</h1>
            <p className="kern-documents-lead">
              Build grounded cases for{" "}
              <code className="kern-test-design-ticket">
                {draft.ticket_identifier}
              </code>
              .
            </p>
          </div>
          <div className="kern-test-design-meta" aria-label="Draft status">
            <span className="kern-status">{formatStatus(draft.status)}</span>
            <span className="kern-status">v{draft.version}</span>
            <span className="kern-status">
              {selectedCount}/{draft.candidates.length} selected
            </span>
            <span className="kern-status" role="status" aria-live="polite">
              {autosaving ? "Saving…" : dirty || casesDirty ? "Unsaved changes" : "Saved"}
            </span>
          </div>
        </div>
        <nav
          className="kern-test-design-progress"
          aria-label="Workflow progress"
        >
          <ol className="kern-test-design-progress__track">
            {WORKSPACE_STEPS.map((item, index) => {
              const currentIndex = WORKSPACE_STEPS.findIndex((s) => s.id === step);
              const state =
                item.id === step
                  ? "current"
                  : index < currentIndex
                    ? "done"
                    : "upcoming";
              const action = stepAction(item.id);
              const content = (
                <>
                  <span
                    className="kern-test-design-progress__node"
                    aria-hidden="true"
                  >
                    {state === "done" ? (
                      <svg
                        className="kern-test-design-progress__check"
                        viewBox="0 0 16 16"
                        focusable="false"
                      >
                        <path
                          d="M3.5 8.2 6.6 11.2 12.5 4.8"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="1.8"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                      </svg>
                    ) : (
                      index + 1
                    )}
                  </span>
                  <span className="kern-test-design-progress__label">
                    {item.label}
                  </span>
                </>
              );
              return (
                <li
                  key={item.id}
                  className={`kern-test-design-progress__step kern-test-design-progress__step--${state}`}
                  aria-current={state === "current" ? "step" : undefined}
                >
                  {action ? (
                    <button
                      type="button"
                      className="kern-test-design-progress__target"
                      onClick={action}
                    >
                      {content}
                    </button>
                  ) : (
                    <span className="kern-test-design-progress__target">
                      {content}
                    </span>
                  )}
                </li>
              );
            })}
          </ol>
        </nav>
      </header>

      {error ? (
        <div
          className="kern-settings-callout kern-settings-callout--error"
          role="alert"
        >
          <p>{error}</p>
        </div>
      ) : null}
      {saveNote ? (
        <div
          className="kern-settings-callout kern-settings-callout--ok"
          role="status"
        >
          <p>{saveNote}</p>
        </div>
      ) : null}
      {xrayReceipt ? (
        <div
          className="kern-settings-callout kern-settings-callout--ok"
          role="status"
        >
          <p>
            Created {xrayReceipt.created_count} test
            {xrayReceipt.created_count === 1 ? "" : "s"} in{" "}
            {xrayReceipt.project_key}:{" "}
            {xrayReceipt.created_keys.map((key, index) => (
              <span key={key}>
                {index > 0 ? ", " : null}
                {xrayReceipt.browse_base_url ? (
                  <a
                    href={`${xrayReceipt.browse_base_url}${encodeURIComponent(key)}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {key}
                  </a>
                ) : (
                  key
                )}
              </span>
            ))}
            {xrayReceipt.failed_count > 0
              ? `. ${xrayReceipt.failed_count} failed.`
              : "."}
          </p>
        </div>
      ) : null}

      {showCoveragePanel ? (
      <fieldset className="kern-settings-fieldset kern-test-design-panel">
        <legend className="visually-hidden">Test selection</legend>
        <p className="kern-settings-hint">{stepHint}</p>
        <div className="kern-test-design-groups">
          {groupCandidatesByCategory(draft.candidates).map((group) => {
            const selectedInGroup = group.candidates.filter(
              (candidate) => candidate.selected,
            ).length;
            const canAdd = draft.candidates.length < MAX_CANDIDATES;
            return (
              <details
                key={group.category}
                className="kern-settings-details kern-test-design-group"
                open
              >
                <summary>
                  <span className="kern-test-design-group__title">
                    {formatCategory(group.category)}
                  </span>
                  <span className="kern-status">
                    {selectedInGroup}/{group.candidates.length} selected
                  </span>
                </summary>
                <ul className="kern-test-design-candidates">
                  {group.candidates.map((candidate) => (
                    <li key={candidate.candidate_id}>
                      <div className="kern-test-design-candidate">
                        <div className="kern-test-design-candidate__select">
                          <label
                            className="kern-test-design-check"
                            htmlFor={`candidate-selected-${candidate.candidate_id}`}
                          >
                            <input
                              id={`candidate-selected-${candidate.candidate_id}`}
                              type="checkbox"
                              checked={candidate.selected}
                              disabled={busy}
                              aria-label={`Keep ${candidate.title || "candidate"}`}
                              onChange={() =>
                                toggleCandidate(candidate.candidate_id)
                              }
                            />
                            <svg
                              className="kern-test-design-check__mark"
                              viewBox="0 0 16 16"
                              aria-hidden="true"
                              focusable="false"
                            >
                              <path
                                d="M3.5 8.2 6.4 11l6.1-6.6"
                                fill="none"
                                stroke="currentColor"
                                strokeWidth="2"
                                strokeLinecap="round"
                                strokeLinejoin="round"
                              />
                            </svg>
                          </label>
                        </div>
                        <div className="kern-test-design-candidate__body">
                          <div className="kern-test-design-candidate__headline">
                            <div className="kern-test-design-candidate__title-control">
                              <input
                                id={`candidate-title-${candidate.candidate_id}`}
                                className="kern-settings-input kern-test-design-candidate__title-input"
                                type="text"
                                value={candidate.title}
                                maxLength={MAX_TITLE_CHARS}
                                placeholder="Enter or edit test title"
                                aria-label="Test title"
                                disabled={busy}
                                onChange={(event) =>
                                  updateCandidateTitle(
                                    candidate.candidate_id,
                                    event.target.value,
                                  )
                                }
                              />
                              <svg
                                className="kern-test-design-candidate__edit-icon"
                                viewBox="0 0 16 16"
                                aria-hidden="true"
                                focusable="false"
                              >
                                <path
                                  d="M11.3 2.3a1.2 1.2 0 0 1 1.7 1.7L5.8 11.2 3 12l.8-2.8 7.5-6.9Z"
                                  fill="none"
                                  stroke="currentColor"
                                  strokeWidth="1.4"
                                  strokeLinejoin="round"
                                />
                              </svg>
                            </div>
                            {showTypeControls ? (
                              <div
                                className="kern-test-design-type-palette"
                                role="group"
                                aria-label={`Test type for ${candidate.title || "candidate"}`}
                              >
                                {(
                                  [
                                    { value: "manual", label: "Manual" },
                                    { value: "cucumber", label: "Cucumber" },
                                  ] as const
                                ).map((option) => {
                                  const pressed = candidate.test_type === option.value;
                                  return (
                                    <button
                                      key={option.value}
                                      type="button"
                                      className={
                                        pressed
                                          ? "kern-test-design-type-palette__option is-active"
                                          : "kern-test-design-type-palette__option"
                                      }
                                      aria-pressed={pressed}
                                      disabled={busy}
                                      onClick={() =>
                                        updateCandidateTestType(
                                          candidate.candidate_id,
                                          option.value,
                                        )
                                      }
                                    >
                                      {option.label}
                                    </button>
                                  );
                                })}
                              </div>
                            ) : null}
                          </div>
                        </div>
                        {candidate.origin === "manual" ? (
                          <Button
                            type="button"
                            variant="ghost"
                            className="kern-test-design-candidate__remove"
                            disabled={busy}
                            aria-label={`Remove candidate ${candidate.title || candidate.category}`}
                            onClick={() =>
                              removeCandidate(candidate.candidate_id)
                            }
                          >
                            Remove
                          </Button>
                        ) : null}
                      </div>
                    </li>
                  ))}
                </ul>
                <div className="kern-test-design-group__add">
                  <Button
                    type="button"
                    variant="secondary"
                    disabled={busy || !canAdd}
                    onClick={() => addCandidate(group.category)}
                  >
                    Add {formatCategory(group.category)} test
                  </Button>
                </div>
              </details>
            );
          })}
        </div>
      </fieldset>
      ) : null}

      {showCasesPanel ? (
        generatedCases.length === 0 ? (
          <fieldset className="kern-settings-fieldset kern-test-design-panel">
            <legend className="visually-hidden">Test steps</legend>
            <p className="kern-settings-hint">{stepHint}</p>
            <p className="kern-settings-hint">No cases generated yet.</p>
          </fieldset>
        ) : (
            <div
              className="kern-test-design-case-packages kern-test-design-panel"
              role="group"
              aria-label="Test steps"
            >
              {hasCucumberCases ? (
                <section
                  className="kern-settings-fieldset kern-test-design-package"
                  aria-label="Cucumber package"
                >
                  <section
                    className="kern-test-design-cucumber-shared"
                    aria-label="Shared Cucumber Feature"
                  >
                    <div className="kern-test-design-keyword-line">
                      <h2 className="kern-test-design-package__title kern-test-design-keyword">
                        Feature:
                      </h2>
                      <input
                        className="kern-settings-input"
                        type="text"
                        value={draft.cucumber_feature ?? ""}
                        disabled={busy}
                        placeholder="Feature title"
                        aria-label="Cucumber feature title"
                        onChange={(event) =>
                          updateCucumberShared({
                            cucumber_feature: event.target.value,
                          })
                        }
                      />
                    </div>
                    <div className="kern-test-design-case__field">
                      <span className="kern-test-design-keyword">Background:</span>
                      {showBackground ? (
                        <>
                          <textarea
                            className="kern-test-design-case__textarea kern-test-design-case__textarea--mono"
                            value={draft.cucumber_background ?? ""}
                            disabled={busy}
                            rows={4}
                            aria-label="Cucumber background steps"
                            onChange={(event) => {
                              setBackgroundOpen(true);
                              updateCucumberShared({
                                cucumber_background: event.target.value,
                              });
                            }}
                          />
                          <Button
                            type="button"
                            variant="secondary"
                            disabled={busy}
                            onClick={() => {
                              setBackgroundOpen(false);
                              updateCucumberShared({ cucumber_background: "" });
                            }}
                          >
                            Remove background
                          </Button>
                        </>
                      ) : (
                        <Button
                          type="button"
                          variant="secondary"
                          disabled={busy}
                          onClick={() => setBackgroundOpen(true)}
                        >
                          Add background
                        </Button>
                      )}
                    </div>
                  </section>
                  <ul className="kern-test-design-scenarios">
                    {cucumberCases.map((item) => {
                      const title =
                        candidateTitleById.get(item.candidate_id)?.trim() ||
                        item.candidate_id;
                      return (
                        <li key={item.candidate_id}>
                          <article className="kern-test-design-case">
                            <header className="kern-test-design-case__head">
                              <div className="kern-test-design-keyword-line kern-test-design-case__name">
                                <h3 className="kern-test-design-keyword">
                                  Scenario:
                                </h3>
                                <input
                                  className="kern-settings-input"
                                  type="text"
                                  value={
                                    candidateTitleById.get(item.candidate_id) ??
                                    ""
                                  }
                                  disabled={busy}
                                  maxLength={MAX_TITLE_CHARS}
                                  placeholder="Scenario name"
                                  aria-label="Scenario name"
                                  onChange={(event) =>
                                    updateCandidateTitle(
                                      item.candidate_id,
                                      event.target.value,
                                    )
                                  }
                                />
                              </div>
                            </header>
                            <label className="kern-test-design-case__field">
                              <textarea
                                className="kern-test-design-case__textarea kern-test-design-case__textarea--mono"
                                value={item.gherkin}
                                disabled={busy}
                                rows={6}
                                placeholder={"Given …\nWhen …\nThen …"}
                                aria-label={`Scenario steps for ${title}`}
                                onChange={(event) =>
                                  updateGeneratedCase(item.candidate_id, {
                                    gherkin: event.target.value,
                                  })
                                }
                              />
                            </label>
                          </article>
                        </li>
                      );
                    })}
                  </ul>
                </section>
              ) : null}

              {hasManualCases ? (
                <section
                  className="kern-settings-fieldset kern-test-design-package"
                  aria-label="Manual package"
                >
                  <h2 className="kern-test-design-package__title">Manual</h2>
                  <p className="kern-settings-hint">
                    Each test lists Preconditions, Steps, and Expected Result.
                    Export adapters map this shape outbound.
                  </p>
                  <ul className="kern-test-design-scenarios">
                    {manualCases.map((item) => {
                      const preconditions = splitPreconditionLines(
                        item.preconditions,
                      );
                      const steps = normalizeStepLines(item.steps);
                      const expectedResults = normalizeExpectedLines(
                        item.expected_result ?? "",
                      );
                      return (
                        <li key={item.candidate_id}>
                          <article className="kern-test-design-case">
                            <header className="kern-test-design-case__head">
                              <div className="kern-test-design-keyword-line kern-test-design-case__name">
                                <h3 className="kern-test-design-keyword">
                                  Title:
                                </h3>
                                <input
                                  className="kern-settings-input"
                                  type="text"
                                  value={
                                    candidateTitleById.get(item.candidate_id) ??
                                    ""
                                  }
                                  disabled={busy}
                                  maxLength={MAX_TITLE_CHARS}
                                  placeholder="Test title"
                                  aria-label="Test title"
                                  onChange={(event) =>
                                    updateCandidateTitle(
                                      item.candidate_id,
                                      event.target.value,
                                    )
                                  }
                                />
                              </div>
                            </header>
                            <div className="kern-test-design-case__field">
                              <span
                                id={`case-preconditions-${item.candidate_id}`}
                              >
                                Preconditions
                              </span>
                              <NumberedListEditor
                                itemLabel="Precondition"
                                labelledBy={`case-preconditions-${item.candidate_id}`}
                                items={preconditions}
                                minItems={0}
                                disabled={busy}
                                onChange={(next) =>
                                  updateGeneratedCase(item.candidate_id, {
                                    preconditions: joinPreconditionLines(next),
                                  })
                                }
                              />
                              <Button
                                type="button"
                                variant="secondary"
                                disabled={
                                  busy || preconditions.length >= MAX_CASE_LINES
                                }
                                onClick={() =>
                                  updateGeneratedCase(item.candidate_id, {
                                    preconditions: joinPreconditionLines([
                                      ...preconditions,
                                      "",
                                    ]),
                                  })
                                }
                              >
                                Add precondition
                              </Button>
                            </div>
                            <div className="kern-test-design-case__field">
                              <span id={`case-steps-${item.candidate_id}`}>
                                Steps
                              </span>
                              <NumberedListEditor
                                itemLabel="Step"
                                labelledBy={`case-steps-${item.candidate_id}`}
                                items={steps}
                                minItems={1}
                                disabled={busy}
                                onChange={(next) =>
                                  updateGeneratedCase(item.candidate_id, {
                                    steps: next,
                                  })
                                }
                              />
                              <Button
                                type="button"
                                variant="secondary"
                                disabled={busy || steps.length >= MAX_CASE_LINES}
                                onClick={() =>
                                  updateGeneratedCase(item.candidate_id, {
                                    steps: [...steps, ""],
                                  })
                                }
                              >
                                Add step
                              </Button>
                            </div>
                            <div className="kern-test-design-case__field">
                              <span
                                id={`case-expected-${item.candidate_id}`}
                              >
                                Expected Result
                              </span>
                              <NumberedListEditor
                                itemLabel="Expected result"
                                labelledBy={`case-expected-${item.candidate_id}`}
                                items={expectedResults}
                                minItems={1}
                                disabled={busy}
                                onChange={(next) =>
                                  updateGeneratedCase(item.candidate_id, {
                                    expected_result: joinExpectedLines(next),
                                  })
                                }
                              />
                              <Button
                                type="button"
                                variant="secondary"
                                disabled={
                                  busy ||
                                  expectedResults.length >= MAX_CASE_LINES
                                }
                                onClick={() =>
                                  updateGeneratedCase(item.candidate_id, {
                                    expected_result: joinExpectedLines([
                                      ...expectedResults,
                                      "",
                                    ]),
                                  })
                                }
                              >
                                Add expected result
                              </Button>
                            </div>
                          </article>
                        </li>
                      );
                    })}
                  </ul>
                </section>
              ) : null}

              {hasClarificationCases ? (
                <section
                  className="kern-settings-fieldset kern-test-design-package"
                  aria-label="Needs more detail from the ticket"
                >
                  <h2 className="kern-test-design-package__title">
                    Needs more detail from the ticket
                  </h2>
                  <p className="kern-settings-hint">
                    The ticket doesn&apos;t describe enough to write these steps
                    without guessing. Write them yourself, remove the test, or
                    update the ticket and regenerate.
                  </p>
                  <ul className="kern-test-design-scenarios">
                    {clarificationCases.map((item) => {
                      const title =
                        candidateTitleById.get(item.candidate_id)?.trim() ||
                        item.candidate_id;
                      return (
                        <li key={item.candidate_id}>
                          <article className="kern-test-design-case">
                            <header className="kern-test-design-case__head">
                              <h3 className="kern-test-design-case__title">
                                {title}
                              </h3>
                            </header>
                            {item.automation_rationale ? (
                              <p className="kern-settings-hint kern-test-design-case__rationale">
                                <strong>What&apos;s missing: </strong>
                                {item.automation_rationale}
                              </p>
                            ) : null}
                            <p role="status" className="kern-settings-hint">
                              No steps were generated, to avoid guessing.
                            </p>
                            <div className="kern-test-design-case__actions">
                              <Button
                                type="button"
                                disabled={busy}
                                onClick={() =>
                                  writeCaseManually(item.candidate_id)
                                }
                              >
                                Write steps manually
                              </Button>
                              <Button
                                type="button"
                                variant="secondary"
                                disabled={actionsLocked || selectedCount <= 1}
                                onClick={() =>
                                  void removeFromSelection(item.candidate_id)
                                }
                              >
                                Remove from selection
                              </Button>
                              <Button
                                type="button"
                                variant="secondary"
                                disabled={!canRegenerate}
                                onClick={() =>
                                  void regenerateCase(item.candidate_id)
                                }
                              >
                                Regenerate
                              </Button>
                            </div>
                          </article>
                        </li>
                      );
                    })}
                  </ul>
                </section>
              ) : null}
            </div>
        )
      ) : null}

      <footer className="kern-test-design-actions">
        <Button
          type="button"
          variant="secondary"
          disabled={actionsLocked}
          onClick={requestExit}
        >
          Exit
        </Button>
        <div className="kern-test-design-actions__primary">
          {showNext ? (
            <Button
              type="button"
              disabled={!canNext}
              onClick={() => void goNext()}
            >
              Next
            </Button>
          ) : (
            <>
              <Button
                type="button"
                variant="secondary"
                disabled={actionsLocked}
                onClick={() => void goBackToCoverage()}
              >
                Back
              </Button>
              <Button
                type="button"
                disabled={!canExport}
                onClick={() => void openExportDialog()}
              >
                Export to Google Drive
              </Button>
              {xrayStatus?.available ? (
                <Button
                  type="button"
                  disabled={!canCreateInXray}
                  onClick={() => void openXrayDialog()}
                >
                  Create in Xray
                </Button>
              ) : null}
            </>
          )}
        </div>
      </footer>

      <ConfirmDialog
        open={exitOpen}
        title="Leave Test Design?"
        description="You have unsaved changes. Save them to this draft before going back to chat?"
        confirmLabel="Save and exit"
        secondaryLabel="Exit without saving"
        cancelLabel="Keep editing"
        busy={busy}
        onConfirm={() => void saveAndExit()}
        onSecondary={() => {
          setExitOpen(false);
          router.push(chatHref);
        }}
        onCancel={() => setExitOpen(false)}
      />

      <ConfirmDialog
        open={xrayOpen}
        title="Create Xray tests"
        description={xrayConfirmText(xrayStatus, xrayCount)}
        confirmLabel={xrayStatus?.created_keys.length ? "Create again" : "Create"}
        busy={busy}
        onConfirm={() => void createInXray()}
        onCancel={() => {
          if (!busy) {
            setXrayOpen(false);
          }
        }}
      />

      <GoogleDrivePicker
        open={exportOpen}
        apiBaseUrl={apiBaseUrl}
        initialSelection={{ folders: [], files: [] }}
        busy={busy}
        foldersOnly
        singleSelect
        title="Export to Google Drive"
        description="Choose the Drive folder that should receive the Markdown export."
        confirmLabel="Export"
        onCancel={() => {
          if (!busy) {
            setExportOpen(false);
          }
        }}
        onConfirm={(selection) => {
          const folder = selection.folders?.[0];
          if (!folder) {
            return;
          }
          void exportSelectedFolder(folder.id, folder.name);
        }}
      />
    </section>
  );
}
