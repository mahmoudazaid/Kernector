"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/Button";
import { Loader } from "@/components/ui/Loader";
import { LoadingState } from "@/components/states/LoadingState";
import { UnavailableState } from "@/components/states/UnavailableState";
import {
  confirmTestDesignDraft,
  getTestDesignDraft,
  patchTestDesignDraft,
  type TestCoverageDraftResponse,
} from "@/lib/api/test-design";
import { ApiError } from "@/lib/api/errors";
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

function formatCategory(value: string): string {
  return value.replaceAll("_", " ");
}

function formatStatus(value: string): string {
  return value.replaceAll("_", " ");
}

const MAX_CANDIDATES = 40;
const MAX_TITLE_CHARS = 200;

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

  async function saveDraft() {
    if (!draft) {
      return;
    }
    const blankTitle = draft.candidates.find(
      (candidate) => !candidate.title.trim(),
    );
    if (blankTitle) {
      setError("Every candidate needs a title before saving.");
      setSaveNote(null);
      return;
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
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409) {
        setError(
          "This draft changed elsewhere. Your unsaved edits are still on screen — reload to discard them, or save again after refreshing.",
        );
      } else {
        setError("Could not save draft.");
      }
    } finally {
      setBusy(false);
    }
  }

  function markDirty() {
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

  async function confirmDraft() {
    if (!draft || dirty || selectedCount === 0) {
      return;
    }
    setBusy(true);
    setError(null);
    setSaveNote(null);
    try {
      const confirmed = await confirmTestDesignDraft({
        baseUrl: apiBaseUrl,
        draftId: draft.draft_id,
        body: { expected_version: draft.version },
      });
      setDraft(confirmed);
      setDirty(false);
      setSaveNote("Draft confirmed.");
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409) {
        setError(
          "This draft changed elsewhere. Your unsaved edits are still on screen — reload to discard them, or refresh before confirming.",
        );
      } else {
        setError("Could not confirm draft.");
      }
    } finally {
      setBusy(false);
    }
  }

  const selectedCount = draft.candidates.filter((c) => c.selected).length;
  const canConfirm = selectedCount > 0 && !busy && !dirty;
  const chatHref = `/chat/${encodeURIComponent(draft.conversation_id)}`;

  return (
    <section className="kern-test-design" aria-busy={busy}>
      {busy ? (
        <div className="kern-test-design-busy" aria-hidden="true">
          <Loader label="Working" size="md" />
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
              Review candidates for{" "}
              <code className="kern-test-design-ticket">
                {draft.ticket_identifier}
              </code>
              . Edit titles, add tests, select which to keep, then save.
            </p>
          </div>
          <div className="kern-test-design-meta" aria-label="Draft status">
            <span className="kern-status">{formatStatus(draft.status)}</span>
            <span className="kern-status">v{draft.version}</span>
            <span className="kern-status">
              {selectedCount}/{draft.candidates.length} selected
            </span>
          </div>
        </div>
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

      <fieldset className="kern-settings-fieldset kern-test-design-panel">
        <legend>Candidates</legend>
        <p className="kern-settings-hint">
          Titles are editable fields. Change a title or add a candidate, select
          which to keep, then save.
        </p>
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
                          <div className="kern-test-design-candidate__title-control">
                            <input
                              id={`candidate-title-${candidate.candidate_id}`}
                              className="kern-settings-input kern-test-design-candidate__title-input"
                              type="text"
                              value={candidate.title}
                              maxLength={MAX_TITLE_CHARS}
                              placeholder="Enter or edit test title"
                              aria-label="Test title"
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

      {draft.coverage_gaps.length > 0 ? (
        <section className="kern-settings-fieldset kern-test-design-panel">
          <h2>Coverage gaps</h2>
          <ul className="kern-test-design-gaps">
            {draft.coverage_gaps.map((gap) => (
              <li key={`${gap.category}-${gap.detail}`}>
                <strong>{formatCategory(gap.category)}</strong>
                <span>{gap.detail}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <footer className="kern-test-design-actions">
        <div className="kern-test-design-actions__primary">
          <Button
            type="button"
            disabled={busy}
            onClick={() => void saveDraft()}
          >
            Save draft
          </Button>
          <Button
            type="button"
            disabled={!canConfirm}
            onClick={() => void confirmDraft()}
          >
            Confirm
          </Button>
        </div>
        <Button
          type="button"
          variant="secondary"
          disabled={busy}
          onClick={() => router.push(chatHref)}
        >
          Back to chat
        </Button>
      </footer>
    </section>
  );
}
