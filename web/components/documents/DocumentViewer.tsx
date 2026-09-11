"use client";

import { useEffect, useRef, useState } from "react";
import type { ApiBlobResult } from "@/lib/api/client";
import {
  getDocumentContent,
  type DocumentBlobOptions,
} from "@/lib/api/documents";
import { ApiError } from "@/lib/api/errors";

type DocumentBlobLoader = (
  options: DocumentBlobOptions,
) => Promise<ApiBlobResult>;

type ViewerState =
  | { kind: "loading" }
  | { kind: "pdf"; url: string }
  | { kind: "text"; text: string }
  | { kind: "unsupported" };

export type DocumentViewerProps = {
  sourceId: string;
  fileName: string;
  contentFormat: string;
  baseUrl: string;
  /** Bumped by the parent after replace so the same source_id reloads. */
  refreshToken?: number;
  getContent?: DocumentBlobLoader;
  onError: (error: ApiError) => void;
};

function mimeTypeForFormat(contentFormat: string): string | null {
  const normalized = contentFormat.toLowerCase();
  if (normalized === "pdf") {
    return "application/pdf";
  }
  if (normalized === "txt" || normalized === "markdown") {
    return "text/plain";
  }
  return null;
}

function asApiError(error: unknown): ApiError {
  return error instanceof ApiError ? error : ApiError.generic(0);
}

export function DocumentViewer({
  sourceId,
  fileName,
  contentFormat,
  baseUrl,
  refreshToken = 0,
  getContent = getDocumentContent,
  onError,
}: DocumentViewerProps) {
  const [state, setState] = useState<ViewerState>({ kind: "loading" });
  const sequenceRef = useRef(0);

  useEffect(() => {
    const mimeType = mimeTypeForFormat(contentFormat);
    if (!mimeType) {
      setState({ kind: "unsupported" });
      return;
    }

    const controller = new AbortController();
    const sequence = ++sequenceRef.current;
    let objectUrl: string | null = null;
    setState({ kind: "loading" });

    getContent({
      baseUrl,
      sourceId,
      signal: controller.signal,
    })
      .then(async ({ blob }) => {
        if (sequence !== sequenceRef.current || controller.signal.aborted) {
          return;
        }
        const displayBlob = new Blob([blob], { type: mimeType });
        if (mimeType === "application/pdf") {
          objectUrl = URL.createObjectURL(displayBlob);
          setState({ kind: "pdf", url: objectUrl });
          return;
        }
        const text = await displayBlob.text();
        if (sequence !== sequenceRef.current || controller.signal.aborted) {
          return;
        }
        setState({ kind: "text", text });
      })
      .catch((error) => {
        if (sequence !== sequenceRef.current || controller.signal.aborted) {
          return;
        }
        onError(asApiError(error));
      });

    return () => {
      controller.abort();
      sequenceRef.current += 1;
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [baseUrl, contentFormat, getContent, onError, refreshToken, sourceId]);

  return (
    <section className="kern-document-viewer" aria-label={`Preview ${fileName}`}>
      <div className="kern-document-viewer-head">
        <h3>{fileName}</h3>
      </div>
      {state.kind === "loading" ? (
        <p className="kern-settings-hint" role="status">
          Loading preview…
        </p>
      ) : null}
      {state.kind === "pdf" ? (
        <iframe
          className="kern-document-viewer-frame"
          title={`Preview of ${fileName}`}
          src={state.url}
          sandbox="allow-scripts"
        />
      ) : null}
      {state.kind === "text" ? (
        <pre className="kern-document-viewer-text">{state.text}</pre>
      ) : null}
      {state.kind === "unsupported" ? (
        <p className="kern-settings-hint" role="status">
          Preview is not available for this document format.
        </p>
      ) : null}
    </section>
  );
}
