"use client";

import {
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
  type RefObject,
} from "react";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/Accordion";
import { Button } from "@/components/ui/Button";
import { Sheet } from "@/components/ui/Sheet";
import type {
  CatalogDocumentResponse,
  DocumentChunkResponse,
} from "@/lib/api/documents";
import { formatTimestamp } from "@/lib/format/timestamp";

export type ChunksSheetView =
  | { kind: "idle" }
  | { kind: "loading" }
  | {
      kind: "ready";
      chunks: DocumentChunkResponse[];
      hasMore: boolean;
      loadMoreError: string | null;
    }
  | { kind: "empty" }
  | { kind: "not_found" }
  | { kind: "error"; message: string };

export type DocumentChunksSheetProps = {
  open: boolean;
  document: CatalogDocumentResponse | null;
  chunksView: ChunksSheetView;
  loadingMore: boolean;
  restoreFocusRef: RefObject<HTMLElement | null>;
  onDismiss: () => void;
  onRetry: () => void;
  onLoadMore: () => void;
};

const PREVIEW_CHARS = 96;

/** Location labels from known ``extra`` keys only — never parsed from content. */
export function chunkLocationLabel(
  extra: Record<string, string>,
): string | null {
  if (typeof extra.page === "string" && extra.page.trim()) {
    return `Page ${extra.page.trim()}`;
  }
  if (
    typeof extra.source_location === "string" &&
    extra.source_location.trim()
  ) {
    return extra.source_location.trim();
  }
  if (typeof extra.location === "string" && extra.location.trim()) {
    return extra.location.trim();
  }
  return null;
}

export function chunkPreview(content: string): string {
  const trimmed = content.replace(/\s+/g, " ").trim();
  if (trimmed.length <= PREVIEW_CHARS) {
    return trimmed;
  }
  return `${trimmed.slice(0, PREVIEW_CHARS).trimEnd()}…`;
}

function chunkDisplayIndex(index: number): string {
  return String(index + 1).padStart(2, "0");
}

function statusLabel(status: string): string {
  if (!status) {
    return status;
  }
  return status.charAt(0).toUpperCase() + status.slice(1);
}

function SearchIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <circle cx="8.5" cy="8.5" r="5.5" stroke="currentColor" strokeWidth="1.5" />
      <path
        d="M12.5 12.5 16 16"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

function CloseIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <path
        d="M5 5 15 15M15 5 5 15"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

function CopyIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <rect
        x="7"
        y="7"
        width="9"
        height="9"
        rx="1.5"
        stroke="currentColor"
        strokeWidth="1.5"
      />
      <path
        d="M13 7V5.5A1.5 1.5 0 0 0 11.5 4h-7A1.5 1.5 0 0 0 3 5.5v7A1.5 1.5 0 0 0 4.5 14H6"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

function ChunkCopyButton({ content }: { content: string }) {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) {
      return;
    }
    const timer = window.setTimeout(() => setCopied(false), 1000);
    return () => window.clearTimeout(timer);
  }, [copied]);

  return (
    <button
      type="button"
      className="kern-chunk-copy"
      onClick={() => {
        void navigator.clipboard.writeText(content).then(
          () => {
            setCopied(true);
          },
          () => {
            setCopied(false);
          },
        );
      }}
    >
      <CopyIcon />
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

export function DocumentChunksSheet({
  open,
  document: doc,
  chunksView,
  loadingMore,
  restoreFocusRef,
  onDismiss,
  onRetry,
  onLoadMore,
}: DocumentChunksSheetProps) {
  const searchRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const deferredQuery = useDeferredValue(query);

  useEffect(() => {
    if (!open) {
      setQuery("");
    }
  }, [open]);

  const filteredChunks = useMemo(() => {
    if (chunksView.kind !== "ready") {
      return [];
    }
    const needle = deferredQuery.trim().toLowerCase();
    if (!needle) {
      return chunksView.chunks;
    }
    return chunksView.chunks.filter((chunk) => {
      const location = chunkLocationLabel(chunk.extra) ?? "";
      return (
        chunk.content.toLowerCase().includes(needle) ||
        location.toLowerCase().includes(needle) ||
        String(chunk.index).includes(needle) ||
        (chunk.title ?? "").toLowerCase().includes(needle)
      );
    });
  }, [chunksView, deferredQuery]);

  const showingCount =
    chunksView.kind === "ready" ? filteredChunks.length : 0;
  const hasFilter = deferredQuery.trim().length > 0;

  if (!doc) {
    return null;
  }

  return (
    <Sheet
      open={open}
      titleId="hub-chunks-title"
      panelClassName="kern-chunks-sheet"
      initialFocusRef={searchRef}
      restoreFocusRef={restoreFocusRef}
      onDismiss={onDismiss}
    >
      <div className="kern-chunks-sheet-head">
        <div className="kern-chunks-sheet-top">
          <div>
            <h2 id="hub-chunks-title" className="kern-chunks-sheet-title">
              {doc.file_name}
            </h2>
            <div className="kern-chunks-sheet-meta">
              <span className={doc.status === "ready" ? "kern-doc-ready" : undefined}>
                {statusLabel(doc.status)}
              </span>
              <span>
                {doc.chunk_count} chunk{doc.chunk_count === 1 ? "" : "s"}
              </span>
              <time dateTime={doc.uploaded_at}>
                {formatTimestamp(doc.uploaded_at)}
              </time>
            </div>
          </div>
          <button
            type="button"
            className="kern-chunks-sheet-close"
            aria-label="Close chunks"
            onClick={onDismiss}
          >
            <CloseIcon />
          </button>
        </div>
        <label className="kern-chunks-sheet-search">
          <span className="visually-hidden">Search chunks</span>
          <span className="kern-chunks-sheet-search-icon" aria-hidden="true">
            <SearchIcon />
          </span>
          <input
            ref={searchRef}
            type="search"
            placeholder="Search within chunks…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            disabled={chunksView.kind === "loading"}
          />
        </label>
      </div>

      <div className="kern-chunks-sheet-body">
        {chunksView.kind === "loading" ? (
          <p className="kern-settings-hint" role="status">
            Loading stored chunks…
          </p>
        ) : null}

        {chunksView.kind === "empty" ? (
          <p className="kern-chunks-none" role="status">
            No stored chunks for this document.
          </p>
        ) : null}

        {chunksView.kind === "not_found" ? (
          <div
            className="kern-settings-callout kern-settings-callout--warn"
            role="status"
          >
            <p>Document was not found in the catalog.</p>
            <Button type="button" variant="secondary" onClick={onRetry}>
              Retry
            </Button>
          </div>
        ) : null}

        {chunksView.kind === "error" ? (
          <div
            className="kern-settings-callout kern-settings-callout--warn"
            role="status"
          >
            <p>{chunksView.message}</p>
            <Button type="button" variant="secondary" onClick={onRetry}>
              Retry
            </Button>
          </div>
        ) : null}

        {chunksView.kind === "ready" ? (
          <>
            <p className="kern-chunks-result-count" aria-live="polite">
              Showing {showingCount} chunk{showingCount === 1 ? "" : "s"}
              {chunksView.hasMore && !hasFilter ? " (more available)" : ""}
            </p>
            {filteredChunks.length === 0 ? (
              <p className="kern-chunks-none" role="status">
                No matching chunks
              </p>
            ) : (
              <Accordion type="multiple" className="kern-chunks-accordion">
                {filteredChunks.map((chunk, position) => {
                  const location = chunkLocationLabel(chunk.extra);
                  const chars = chunk.content.length;
                  const summaryParts = [
                    location,
                    `${chars} character${chars === 1 ? "" : "s"}`,
                  ].filter(Boolean);
                  const itemValue = `${chunk.source_type}:${chunk.source_id}:${chunk.index}:${position}`;
                  return (
                    <AccordionItem key={itemValue} value={itemValue}>
                      <AccordionTrigger>
                        <span className="kern-chunk-num">
                          {chunkDisplayIndex(chunk.index)}
                        </span>
                        <span className="kern-chunk-summary">
                          <strong>{summaryParts.join(" · ")}</strong>
                          <small>{chunkPreview(chunk.content)}</small>
                        </span>
                      </AccordionTrigger>
                      <AccordionContent>
                        <div className="kern-chunk-content-bar">
                          <span>Chunk ID · {chunk.index}</span>
                          <ChunkCopyButton content={chunk.content} />
                        </div>
                        <pre className="kern-chunk-text">{chunk.content}</pre>
                      </AccordionContent>
                    </AccordionItem>
                  );
                })}
              </Accordion>
            )}
            {chunksView.loadMoreError ? (
              <div
                className="kern-settings-callout kern-settings-callout--warn"
                role="status"
              >
                <p>{chunksView.loadMoreError}</p>
              </div>
            ) : null}
            {chunksView.hasMore && !hasFilter ? (
              <Button
                type="button"
                disabled={loadingMore}
                onClick={onLoadMore}
              >
                {loadingMore ? "Loading…" : "Load more chunks"}
              </Button>
            ) : null}
          </>
        ) : null}
      </div>
    </Sheet>
  );
}
