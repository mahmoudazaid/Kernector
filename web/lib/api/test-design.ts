import { apiRequest, type ApiRequestOptions } from "@/lib/api/client";
import type { components } from "@/lib/api/generated/schema";

export type CreateTestDesignDraftRequest =
  components["schemas"]["CreateTestDesignDraftRequest"];
export type PatchTestDesignDraftRequest =
  components["schemas"]["PatchTestDesignDraftRequest"];
export type ExpectedVersionRequest =
  components["schemas"]["ExpectedVersionRequest"];
export type TestCoverageDraftResponse =
  components["schemas"]["TestCoverageDraftResponse"];

export const TEST_DESIGN_TIMEOUT_MS = 120_000;

type BaseOptions = {
  baseUrl: string;
  signal?: AbortSignal;
  timeoutMs?: number;
  request?: typeof apiRequest;
};

export async function createTestDesignDraft(
  options: BaseOptions & { body: CreateTestDesignDraftRequest },
): Promise<TestCoverageDraftResponse> {
  const request = options.request ?? apiRequest;
  return request<TestCoverageDraftResponse>({
    baseUrl: options.baseUrl,
    path: "/api/v1/test-design/drafts",
    method: "POST",
    body: options.body,
    signal: options.signal,
    timeoutMs: options.timeoutMs ?? TEST_DESIGN_TIMEOUT_MS,
  } satisfies ApiRequestOptions);
}

export async function getTestDesignDraft(
  options: BaseOptions & { draftId: string },
): Promise<TestCoverageDraftResponse> {
  const request = options.request ?? apiRequest;
  return request<TestCoverageDraftResponse>({
    baseUrl: options.baseUrl,
    path: `/api/v1/test-design/drafts/${encodeURIComponent(options.draftId)}`,
    method: "GET",
    signal: options.signal,
    timeoutMs: options.timeoutMs ?? TEST_DESIGN_TIMEOUT_MS,
  } satisfies ApiRequestOptions);
}

export async function patchTestDesignDraft(
  options: BaseOptions & {
    draftId: string;
    body: PatchTestDesignDraftRequest;
  },
): Promise<TestCoverageDraftResponse> {
  const request = options.request ?? apiRequest;
  return request<TestCoverageDraftResponse>({
    baseUrl: options.baseUrl,
    path: `/api/v1/test-design/drafts/${encodeURIComponent(options.draftId)}`,
    method: "PATCH",
    body: options.body,
    signal: options.signal,
    timeoutMs: options.timeoutMs ?? TEST_DESIGN_TIMEOUT_MS,
  } satisfies ApiRequestOptions);
}

export async function generateTestDesignScenarios(
  options: BaseOptions & {
    draftId: string;
    body: ExpectedVersionRequest;
  },
): Promise<TestCoverageDraftResponse> {
  const request = options.request ?? apiRequest;
  return request<TestCoverageDraftResponse>({
    baseUrl: options.baseUrl,
    path: `/api/v1/test-design/drafts/${encodeURIComponent(options.draftId)}/scenarios`,
    method: "POST",
    body: options.body,
    signal: options.signal,
    timeoutMs: options.timeoutMs ?? TEST_DESIGN_TIMEOUT_MS,
  } satisfies ApiRequestOptions);
}

export async function confirmTestDesignDraft(
  options: BaseOptions & {
    draftId: string;
    body: ExpectedVersionRequest;
  },
): Promise<TestCoverageDraftResponse> {
  const request = options.request ?? apiRequest;
  return request<TestCoverageDraftResponse>({
    baseUrl: options.baseUrl,
    path: `/api/v1/test-design/drafts/${encodeURIComponent(options.draftId)}/confirm`,
    method: "POST",
    body: options.body,
    signal: options.signal,
    timeoutMs: options.timeoutMs ?? TEST_DESIGN_TIMEOUT_MS,
  } satisfies ApiRequestOptions);
}
