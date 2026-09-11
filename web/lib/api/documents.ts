import {
  apiRequest,
  apiRequestBlob,
  type ApiRequestOptions,
} from "@/lib/api/client";
import type { components } from "@/lib/api/generated/schema";

export type CatalogDocumentResponse =
  components["schemas"]["CatalogDocumentResponse"];
export type DocumentListResponse =
  components["schemas"]["DocumentListResponse"];

/** Uploads and document byte reads routinely exceed the default 10s timeout. */
export const DOCUMENT_MUTATION_TIMEOUT_MS = 120_000;
/** Alias kept honest for preview/download transfers of non-trivial PDFs. */
export const DOCUMENT_READ_TIMEOUT_MS = DOCUMENT_MUTATION_TIMEOUT_MS;

export type ListDocumentsOptions = {
  baseUrl: string;
  signal?: AbortSignal;
  timeoutMs?: number;
  request?: typeof apiRequest;
};

export type UploadDocumentOptions = {
  baseUrl: string;
  file: File | Blob;
  fileName?: string;
  signal?: AbortSignal;
  timeoutMs?: number;
  request?: typeof apiRequest;
};

export type ReplaceDocumentOptions = UploadDocumentOptions & {
  sourceId: string;
};

export type DeleteDocumentOptions = {
  baseUrl: string;
  sourceId: string;
  signal?: AbortSignal;
  timeoutMs?: number;
  request?: typeof apiRequest;
};

export type DocumentBlobOptions = {
  baseUrl: string;
  sourceId: string;
  signal?: AbortSignal;
  timeoutMs?: number;
  requestBlob?: typeof apiRequestBlob;
};

function filePart(
  file: File | Blob,
  fileName?: string,
): File | Blob {
  if (fileName && !(file instanceof File)) {
    return new File([file], fileName);
  }
  return file;
}

/**
 * List uploaded documents from ``GET /api/v1/documents``.
 */
export async function listDocuments(
  options: ListDocumentsOptions,
): Promise<DocumentListResponse> {
  const request = options.request ?? apiRequest;
  return request<DocumentListResponse>({
    baseUrl: options.baseUrl,
    path: "/api/v1/documents",
    method: "GET",
    signal: options.signal,
    timeoutMs: options.timeoutMs,
  } satisfies ApiRequestOptions);
}

/**
 * Upload a new document via multipart ``POST /api/v1/documents``.
 */
export async function uploadDocument(
  options: UploadDocumentOptions,
): Promise<CatalogDocumentResponse> {
  const request = options.request ?? apiRequest;
  const form = new FormData();
  const name =
    options.fileName ??
    (options.file instanceof File ? options.file.name : "upload.bin");
  form.append("file", filePart(options.file, name), name);
  return request<CatalogDocumentResponse>({
    baseUrl: options.baseUrl,
    path: "/api/v1/documents",
    method: "POST",
    body: form,
    signal: options.signal,
    timeoutMs: options.timeoutMs ?? DOCUMENT_MUTATION_TIMEOUT_MS,
  } satisfies ApiRequestOptions);
}

/**
 * Replace document content via multipart ``PUT /api/v1/documents/{source_id}``.
 */
export async function replaceDocument(
  options: ReplaceDocumentOptions,
): Promise<CatalogDocumentResponse> {
  const request = options.request ?? apiRequest;
  const form = new FormData();
  const name =
    options.fileName ??
    (options.file instanceof File ? options.file.name : "upload.bin");
  form.append("file", filePart(options.file, name), name);
  return request<CatalogDocumentResponse>({
    baseUrl: options.baseUrl,
    path: `/api/v1/documents/${encodeURIComponent(options.sourceId)}`,
    method: "PUT",
    body: form,
    signal: options.signal,
    timeoutMs: options.timeoutMs ?? DOCUMENT_MUTATION_TIMEOUT_MS,
  } satisfies ApiRequestOptions);
}

/**
 * Delete a document via ``DELETE /api/v1/documents/{source_id}``.
 */
export async function deleteDocument(
  options: DeleteDocumentOptions,
): Promise<void> {
  const request = options.request ?? apiRequest;
  await request<undefined>({
    baseUrl: options.baseUrl,
    path: `/api/v1/documents/${encodeURIComponent(options.sourceId)}`,
    method: "DELETE",
    signal: options.signal,
    timeoutMs: options.timeoutMs ?? DOCUMENT_MUTATION_TIMEOUT_MS,
  } satisfies ApiRequestOptions);
}

/**
 * Fetch original upload bytes for inline preview.
 */
export async function getDocumentContent(options: DocumentBlobOptions) {
  const requestBlob = options.requestBlob ?? apiRequestBlob;
  return requestBlob({
    baseUrl: options.baseUrl,
    path: `/api/v1/documents/${encodeURIComponent(options.sourceId)}/content`,
    method: "GET",
    signal: options.signal,
    timeoutMs: options.timeoutMs ?? DOCUMENT_READ_TIMEOUT_MS,
  });
}

/**
 * Fetch original upload bytes for download (attachment disposition).
 */
export async function downloadDocument(options: DocumentBlobOptions) {
  const requestBlob = options.requestBlob ?? apiRequestBlob;
  return requestBlob({
    baseUrl: options.baseUrl,
    path: `/api/v1/documents/${encodeURIComponent(options.sourceId)}/download`,
    method: "GET",
    signal: options.signal,
    timeoutMs: options.timeoutMs ?? DOCUMENT_READ_TIMEOUT_MS,
  });
}
