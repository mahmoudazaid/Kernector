"use client";

import { useEffect, useId, useMemo, useState } from "react";
import { Button } from "@/components/ui/Button";
import { SoftSelect } from "@/components/ui/SoftSelect";
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
const PLACEHOLDER = "Select a document…";

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
  const title =
    typeof doc.title === "string" && doc.title.trim() ? doc.title : null;
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
  const ticketInputId = useId();
  const [documents, setDocuments] = useState<CatalogDocumentResponse[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [sourceKey, setSourceKey] = useState("");
  const [ticket, setTicket] = useState("");

  const labelByKey = useMemo(() => {
    const map = new Map<string, string>();
    const used = new Set<string>();
    for (const doc of documents) {
      const key = sourceOptionKey(doc.source_type, doc.source_id);
      let label = documentLabel(doc);
      if (used.has(label)) {
        label = `${label} (${doc.source_id})`;
      }
      used.add(label);
      map.set(key, label);
    }
    return map;
  }, [documents]);

  const keyByLabel = useMemo(() => {
    const map = new Map<string, string>();
    for (const [key, label] of labelByKey) {
      map.set(label, key);
    }
    return map;
  }, [labelByKey]);

  const selectOptions = useMemo(
    () => [PLACEHOLDER, ...labelByKey.values()],
    [labelByKey],
  );

  const selectedLabel =
    (sourceKey && labelByKey.get(sourceKey)) || PLACEHOLDER;

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

  function handleSourceLabelChange(label: string) {
    if (label === PLACEHOLDER) {
      setSourceKey("");
      return;
    }
    const key = keyByLabel.get(label) ?? "";
    setSourceKey(key);
    const parsed = key ? sourceOptionKeyParts(key) : null;
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
    <fieldset
      className="kern-settings-fieldset kern-chat-test-design-attach"
      disabled={disabled}
    >
      <legend>Test Design context (optional)</legend>
      <div className="kern-chat-test-design-attach__row">
        <div className="kern-chat-test-design-attach__source">
          <SoftSelect
            id="chat-test-design-source"
            label="Source document"
            value={selectedLabel}
            options={selectOptions}
            onChange={handleSourceLabelChange}
          />
        </div>
        <div className="kern-settings-field kern-chat-test-design-attach__ticket-field">
          <label htmlFor={ticketInputId}>Ticket identifier</label>
          <input
            id={ticketInputId}
            className="kern-settings-input"
            type="text"
            placeholder="e.g. issue-8"
            value={ticket}
            disabled={disabled}
            aria-invalid={ticketBare || undefined}
            onChange={(event) => setTicket(event.target.value)}
          />
        </div>
        {sourceKey || ticket ? (
          <Button
            type="button"
            variant="secondary"
            disabled={disabled}
            onClick={clearAttachment}
          >
            Clear
          </Button>
        ) : null}
      </div>
      {loadError ? (
        <p className="kern-settings-hint" role="status">
          {loadError}
        </p>
      ) : null}
      {ticketBare ? (
        <p className="kern-settings-hint" role="status">
          Ticket id cannot be a bare number.
        </p>
      ) : null}
      {sourceKey && ticket.trim() && !ticketBare ? (
        <p className="kern-settings-hint">
          Send a message to get a Start Test Design action for this ticket.
        </p>
      ) : null}
    </fieldset>
  );
}
