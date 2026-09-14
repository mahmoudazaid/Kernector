"use client";

import { useEffect, useId, useState } from "react";
import {
  listDocuments,
  type CatalogDocumentResponse,
} from "@/lib/api/documents";
import {
  buildTestDesignHandoff,
  ticketIdentifierFromFileName,
  type TestDesignHandoff,
  type TestDesignSourceRef,
} from "@/lib/chat/test-design-handoff";

export type ChatTestDesignAttachProps = {
  apiBaseUrl: string;
  disabled?: boolean;
  listDocs?: typeof listDocuments;
  onHandoffChange: (handoff: TestDesignHandoff | null) => void;
};

const SOURCE_KEY_SEP = "::";

function sourceOptionKey(sourceType: string, sourceId: string): string {
  return `${sourceType}${SOURCE_KEY_SEP}${sourceId}`;
}

function sourceOptionKeyParts(
  key: string,
): { source_type: string; source_id: string } | null {
  const sep = key.indexOf(SOURCE_KEY_SEP);
  if (sep <= 0 || sep >= key.length - SOURCE_KEY_SEP.length) {
    return null;
  }
  return {
    source_type: key.slice(0, sep),
    source_id: key.slice(sep + SOURCE_KEY_SEP.length),
  };
}

function documentLabel(doc: CatalogDocumentResponse): string {
  const title = typeof doc.title === "string" && doc.title.trim() ? doc.title : null;
  const name = doc.file_name || doc.source_id;
  return title ? `${name} — ${title}` : name;
}

/**
 * Pack-gated composer attachment: pick a catalog document and ticket id so
 * the next ask can carry an explicit Test Design handoff.
 */
export function ChatTestDesignAttach({
  apiBaseUrl,
  disabled = false,
  listDocs = listDocuments,
  onHandoffChange,
}: ChatTestDesignAttachProps) {
  const sourceSelectId = useId();
  const ticketInputId = useId();
  const [documents, setDocuments] = useState<CatalogDocumentResponse[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [sourceKey, setSourceKey] = useState("");
  const [ticket, setTicket] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    void listDocs({ baseUrl: apiBaseUrl, signal: controller.signal })
      .then((response) => {
        const ready = response.documents.filter(
          (doc) => doc.status === "ready" && !doc.has_error,
        );
        setDocuments(ready);
        setLoadError(null);
      })
      .catch(() => {
        if (controller.signal.aborted) {
          return;
        }
        setDocuments([]);
        setLoadError("Could not load documents for Test Design.");
      });
    return () => controller.abort();
  }, [apiBaseUrl, listDocs]);

  useEffect(() => {
    const parsed = sourceKey ? sourceOptionKeyParts(sourceKey) : null;
    const selected = parsed
      ? documents.find(
          (doc) =>
            doc.source_type === parsed.source_type &&
            doc.source_id === parsed.source_id,
        )
      : undefined;
    const source: TestDesignSourceRef | null = selected
      ? { source_id: selected.source_id, source_type: selected.source_type }
      : null;
    onHandoffChange(buildTestDesignHandoff(source, ticket));
  }, [documents, onHandoffChange, sourceKey, ticket]);

  function handleSourceChange(value: string) {
    setSourceKey(value);
    const parsed = value ? sourceOptionKeyParts(value) : null;
    const selected = parsed
      ? documents.find(
          (doc) =>
            doc.source_type === parsed.source_type &&
            doc.source_id === parsed.source_id,
        )
      : undefined;
    if (!selected) {
      return;
    }
    const suggested = ticketIdentifierFromFileName(selected.file_name);
    if (suggested) {
      setTicket(suggested);
    }
  }

  function clearAttachment() {
    setSourceKey("");
    setTicket("");
  }

  const ticketBare = /^\d+$/u.test(ticket.trim());

  return (
    <div className="kern-chat-test-design-attach">
      <p className="kern-chat-test-design-attach__label">
        Test Design context (optional)
      </p>
      <div className="kern-chat-test-design-attach__row">
        <label className="visually-hidden" htmlFor={sourceSelectId}>
          Source document
        </label>
        <select
          id={sourceSelectId}
          className="kern-chat-test-design-attach__select"
          value={sourceKey}
          disabled={disabled || documents.length === 0}
          onChange={(event) => handleSourceChange(event.target.value)}
        >
          <option value="">Select a document…</option>
          {documents.map((doc) => {
            const key = sourceOptionKey(doc.source_type, doc.source_id);
            return (
              <option key={key} value={key}>
                {documentLabel(doc)}
              </option>
            );
          })}
        </select>
        <label className="visually-hidden" htmlFor={ticketInputId}>
          Ticket identifier
        </label>
        <input
          id={ticketInputId}
          className="kern-chat-test-design-attach__ticket"
          type="text"
          placeholder="Ticket id (e.g. issue-8)"
          value={ticket}
          disabled={disabled}
          aria-invalid={ticketBare || undefined}
          onChange={(event) => setTicket(event.target.value)}
        />
        {sourceKey || ticket ? (
          <button
            type="button"
            className="kern-chat-test-design-attach__clear"
            disabled={disabled}
            onClick={clearAttachment}
          >
            Clear
          </button>
        ) : null}
      </div>
      {loadError ? (
        <p className="kern-chat-test-design-attach__hint" role="status">
          {loadError}
        </p>
      ) : null}
      {ticketBare ? (
        <p className="kern-chat-test-design-attach__hint" role="status">
          Ticket id cannot be a bare number.
        </p>
      ) : null}
      {sourceKey && ticket.trim() && !ticketBare ? (
        <p className="kern-chat-test-design-attach__hint">
          Send a message to get a Start Test Design action for this ticket.
        </p>
      ) : null}
    </div>
  );
}
