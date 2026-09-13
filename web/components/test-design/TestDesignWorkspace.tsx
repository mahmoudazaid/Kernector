"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/Button";
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

type Props = {
  apiBaseUrl: string;
  draftId: string;
};

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
    return <p>Loading…</p>;
  }
  if (!packEnabled) {
    return (
      <UnavailableState
        title="Test Design unavailable"
        description="Enable the Software Delivery pack to use Test Design."
      />
    );
  }
  if (error) {
    return (
      <UnavailableState title="Draft unavailable" description={error} />
    );
  }
  if (!draft) {
    return <p>Loading draft…</p>;
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

  async function generateScenarios() {
    if (!draft) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const updated = await generateTestDesignScenarios({
        baseUrl: apiBaseUrl,
        draftId: draft.draft_id,
        body: { expected_version: draft.version },
      });
      setDraft(updated);
    } catch {
      setError("Could not generate scenarios.");
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
      const ready = await confirmTestDesignDraft({
        baseUrl: apiBaseUrl,
        draftId: draft.draft_id,
        body: { expected_version: draft.version },
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
          ticket_identifier: ready.ticket_identifier,
          source_reference: ready.source_reference,
        },
      };
      updateConversation(originatingId, {
        messages: [...conversation.messages, summary],
        unread: true,
      });
      setConfirmNote("Draft confirmed. A summary was added to the originating chat.");
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409) {
        setError("Version conflict while confirming. Reload and try again.");
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
      return {
        ...current,
        candidates: current.candidates.map((candidate) =>
          candidate.candidate_id === candidateId
            ? { ...candidate, selected: !candidate.selected }
            : candidate,
        ),
        selected_candidate_ids: current.candidates
          .map((candidate) =>
            candidate.candidate_id === candidateId
              ? { ...candidate, selected: !candidate.selected }
              : candidate,
          )
          .filter((candidate) => candidate.selected)
          .map((candidate) => candidate.candidate_id),
      };
    });
  }

  const selectedCount = draft.candidates.filter((c) => c.selected).length;

  return (
    <main className="kern-test-design">
      <header>
        <p>
          <Link href={`/chat/${encodeURIComponent(draft.conversation_id)}`}>
            Back to Chat
          </Link>
        </p>
        <h1>Test Design</h1>
        <p>
          Ticket {draft.ticket_identifier} · status {draft.status} · version{" "}
          {draft.version}
        </p>
        <p>
          Selected {selectedCount} of {draft.candidates.length} candidates
        </p>
      </header>

      {error ? <p role="alert">{error}</p> : null}
      {confirmNote ? <p role="status">{confirmNote}</p> : null}

      <section>
        <h2>Coverage</h2>
        <ul>
          {draft.candidates.map((candidate) => (
            <li key={candidate.candidate_id}>
              <label>
                <input
                  type="checkbox"
                  checked={candidate.selected}
                  onChange={() => toggleCandidate(candidate.candidate_id)}
                />{" "}
                <strong>{candidate.title}</strong> ({candidate.category})
              </label>
              <p>{candidate.rationale}</p>
            </li>
          ))}
        </ul>
        {draft.coverage_gaps.length > 0 ? (
          <>
            <h3>Coverage gaps</h3>
            <ul>
              {draft.coverage_gaps.map((gap) => (
                <li key={`${gap.category}-${gap.detail}`}>
                  <strong>{gap.category}</strong>: {gap.detail}
                </li>
              ))}
            </ul>
          </>
        ) : null}
      </section>

      <section>
        <h2>Scenarios</h2>
        {draft.scenarios.length === 0 ? (
          <p>No scenarios yet. Generate for selected candidates.</p>
        ) : (
          <ul>
            {draft.scenarios.map((scenario) => (
              <li key={scenario.scenario_id}>
                <strong>{scenario.title}</strong>
                <ol>
                  {scenario.steps.map((step) => (
                    <li key={step}>{step}</li>
                  ))}
                </ol>
                <p>Expected: {scenario.expected_result}</p>
              </li>
            ))}
          </ul>
        )}
      </section>

      <footer>
        <Button type="button" disabled={busy} onClick={() => void saveDraft()}>
          Save Draft
        </Button>
        <Button
          type="button"
          disabled={busy || selectedCount === 0}
          onClick={() => void generateScenarios()}
        >
          Generate Scenarios
        </Button>
        <Button
          type="button"
          disabled={busy || draft.status === "ready"}
          onClick={() => void confirmDraft()}
        >
          Confirm
        </Button>
        <Button type="button" onClick={() => router.push("/chat")}>
          Chat
        </Button>
      </footer>
    </main>
  );
}
