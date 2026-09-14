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
  generateTestDesignScenarios,
  getTestDesignDraft,
  patchTestDesignDraft,
  type TestCoverageDraftResponse,
} from "@/lib/api/test-design";
import { ApiError } from "@/lib/api/errors";
import { useRuntimeCatalog } from "@/lib/settings/use-runtime-catalog";
import {
  getConversation,
  updateConversation,
} from "@/lib/session/conversations";
import type { StoredChatMessage } from "@/lib/settings/runtime-settings-storage";

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
    const group = byCategory.get(category);
    if (group && group.length > 0) {
      ordered.push({ category, candidates: group });
      byCategory.delete(category);
    }
  }
  for (const [category, group] of byCategory) {
    ordered.push({ category, candidates: group });
  }
  return ordered;
}

export function TestDesignWorkspace({ apiBaseUrl, draftId }: Props) {
  const router = useRouter();
  const { catalog, loading: catalogLoading } = useRuntimeCatalog(apiBaseUrl);
  const packEnabled = catalog?.enabled_packs.includes(PACK_ID) ?? false;
  const [draft, setDraft] = useState<TestCoverageDraftResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmNote, setConfirmNote] = useState<string | null>(null);

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

  if (catalogLoading) {
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

  if (!packEnabled) {
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
    setBusy(true);
    setError(null);
    try {
      const saved = await patchTestDesignDraft({
        baseUrl: apiBaseUrl,
        draftId: draft.draft_id,
        body: {
          expected_version: draft.version,
          candidates: draft.candidates,
          scenarios: draft.scenarios,
        },
      });
      setDraft(saved);
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

  async function confirmDraft() {
    if (!draft) {
      return;
    }
    setBusy(true);
    setError(null);
    setConfirmNote(null);
    try {
      // Persist checkbox selection first — confirm reads the store, not local state.
      const saved = await patchTestDesignDraft({
        baseUrl: apiBaseUrl,
        draftId: draft.draft_id,
        body: {
          expected_version: draft.version,
          candidates: draft.candidates,
          scenarios: draft.scenarios,
        },
      });
      setDraft(saved);
      const ready = await confirmTestDesignDraft({
        baseUrl: apiBaseUrl,
        draftId: saved.draft_id,
        body: { expected_version: saved.version },
      });
      setDraft(ready);
      const originatingId = ready.conversation_id;
      const conversation = getConversation(originatingId);
      if (!conversation) {
        setConfirmNote(
          "Draft is ready. The originating chat could not be updated because it was deleted.",
        );
        return;
      }
      const summary: StoredChatMessage = {
        id: `td-ready-${ready.draft_id}`,
        role: "assistant",
        content: `Test Design draft ready for ${ready.ticket_identifier}.`,
        action: {
          kind: "open_workflow",
          workflow_id: "software-delivery.test-design",
          label: "Open Test Design draft",
          draft_id: ready.draft_id,
        },
      };
      updateConversation(originatingId, {
        messages: [...conversation.messages, summary],
        unread: true,
      });
      setConfirmNote(
        "Draft confirmed. A summary was added to the originating chat.",
      );
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409) {
        setError("Version conflict while confirming. Reload and try again.");
      } else if (caught instanceof ApiError && caught.status === 422) {
        setError(
          "Select at least one candidate, then confirm again.",
        );
      } else {
        setError("Could not confirm draft.");
      }
    } finally {
      setBusy(false);
    }
  }

  function toggleCandidate(candidateId: string) {
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

  const selectedCount = draft.candidates.filter((c) => c.selected).length;
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
              Review coverage for{" "}
              <code className="kern-test-design-ticket">
                {draft.ticket_identifier}
              </code>
              , select candidates to keep, then confirm the draft.
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
      {confirmNote ? (
        <div
          className="kern-settings-callout kern-settings-callout--ok"
          role="status"
        >
          <p>{confirmNote}</p>
        </div>
      ) : null}

      <fieldset className="kern-settings-fieldset kern-test-design-panel">
        <legend>Candidates</legend>
        <p className="kern-settings-hint">
          Select candidates to keep, then save or confirm the draft.
        </p>
        <div className="kern-test-design-groups">
          {groupCandidatesByCategory(draft.candidates).map((group) => {
            const selectedInGroup = group.candidates.filter(
              (candidate) => candidate.selected,
            ).length;
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
                      <label className="kern-test-design-candidate">
                        <span className="kern-test-design-check">
                          <input
                            type="checkbox"
                            checked={candidate.selected}
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
                        </span>
                        <span className="kern-test-design-candidate__body">
                          <span className="kern-test-design-candidate__title">
                            <strong>{candidate.title}</strong>
                          </span>
                          <span className="kern-test-design-candidate__rationale">
                            {candidate.rationale}
                          </span>
                        </span>
                      </label>
                    </li>
                  ))}
                </ul>
              </details>
            );
          })}
        </div>
      </fieldset>

      <footer className="kern-test-design-actions">
        <div className="kern-test-design-actions__primary">
          <Button
            type="button"
            variant="secondary"
            disabled={busy}
            onClick={() => void saveDraft()}
          >
            Save draft
          </Button>
          <Button
            type="button"
            disabled={busy || selectedCount === 0 || draft.status === "ready"}
            onClick={() => void confirmDraft()}
          >
            Confirm
          </Button>
        </div>
        <Button
          type="button"
          variant="ghost"
          disabled={busy}
          onClick={() => router.push(chatHref)}
        >
          Back to chat
        </Button>
      </footer>
    </section>
  );
}
