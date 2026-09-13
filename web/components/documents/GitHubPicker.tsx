"use client";

import { useEffect, useId, useState } from "react";
import { Button } from "@/components/ui/Button";
import { DialogFrame } from "@/components/ui/DialogFrame";
import { Loader } from "@/components/ui/Loader";
import { ApiError, isAbortError } from "@/lib/api/errors";
import {
  listGitHubProjects,
  listGitHubRepos,
  type GitHubProjectItemResponse,
  type GitHubRepoItemResponse,
  type GitHubSelectionResponse,
  type ListGitHubProjectsOptions,
  type ListGitHubReposOptions,
} from "@/lib/api/connectors";

export type GitHubPickerProps = {
  open: boolean;
  apiBaseUrl: string;
  initialSelection: GitHubSelectionResponse;
  selectionLoading?: boolean;
  busy?: boolean;
  listRepos?: (
    options: ListGitHubReposOptions,
  ) => Promise<{ items: GitHubRepoItemResponse[]; has_next: boolean }>;
  listProjects?: (
    options: ListGitHubProjectsOptions,
  ) => Promise<{
    items: GitHubProjectItemResponse[];
    next_cursor: string | null;
  }>;
  onConfirm: (selection: {
    owner: string;
    repo: string;
    project_owner?: string | null;
    project_number?: number | null;
  }) => void;
  onCancel: () => void;
  notice?: string | null;
};

type BrowseView =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | {
      kind: "ready";
      repos: GitHubRepoItemResponse[];
      hasNext: boolean;
      page: number;
    };

function actionErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.detail;
  }
  if (isAbortError(error)) {
    return "The request was cancelled.";
  }
  return "The request failed. Please try again later.";
}

export function GitHubPicker({
  open,
  apiBaseUrl,
  initialSelection,
  selectionLoading = false,
  busy = false,
  listRepos = listGitHubRepos,
  listProjects = listGitHubProjects,
  onConfirm,
  onCancel,
  notice = null,
}: GitHubPickerProps) {
  const titleId = useId();
  const [view, setView] = useState<BrowseView>({ kind: "loading" });
  const [selectedOwner, setSelectedOwner] = useState<string | null>(
    initialSelection.owner,
  );
  const [selectedRepo, setSelectedRepo] = useState<string | null>(
    initialSelection.repo,
  );
  const [selectedProjectOwner, setSelectedProjectOwner] = useState<
    string | null
  >(initialSelection.project_owner);
  const [selectedProjectNumber, setSelectedProjectNumber] = useState<
    number | null
  >(initialSelection.project_number);
  const [projects, setProjects] = useState<GitHubProjectItemResponse[]>([]);
  const [projectsLoading, setProjectsLoading] = useState(false);
  const [projectsError, setProjectsError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    setSelectedOwner(initialSelection.owner);
    setSelectedRepo(initialSelection.repo);
    setSelectedProjectOwner(initialSelection.project_owner);
    setSelectedProjectNumber(initialSelection.project_number);
  }, [open, initialSelection]);

  useEffect(() => {
    if (!open) {
      return;
    }
    let ignore = false;
    const controller = new AbortController();
    setView({ kind: "loading" });
    void (async () => {
      try {
        const page = await listRepos({
          baseUrl: apiBaseUrl,
          page: 1,
          signal: controller.signal,
        });
        if (ignore) {
          return;
        }
        setView({
          kind: "ready",
          repos: page.items,
          hasNext: page.has_next,
          page: 1,
        });
      } catch (error) {
        if (ignore || isAbortError(error)) {
          return;
        }
        setView({ kind: "error", message: actionErrorMessage(error) });
      }
    })();
    return () => {
      ignore = true;
      controller.abort();
    };
  }, [open, apiBaseUrl, listRepos]);

  useEffect(() => {
    if (!open || !selectedOwner) {
      setProjects([]);
      setProjectsError(null);
      return;
    }
    let ignore = false;
    const controller = new AbortController();
    setProjectsLoading(true);
    setProjectsError(null);
    void (async () => {
      try {
        const page = await listProjects({
          baseUrl: apiBaseUrl,
          ownerLogin: selectedOwner,
          signal: controller.signal,
        });
        if (ignore) {
          return;
        }
        setProjects(page.items);
      } catch (error) {
        if (ignore || isAbortError(error)) {
          return;
        }
        setProjects([]);
        setProjectsError(actionErrorMessage(error));
      } finally {
        if (!ignore) {
          setProjectsLoading(false);
        }
      }
    })();
    return () => {
      ignore = true;
      controller.abort();
    };
  }, [open, apiBaseUrl, listProjects, selectedOwner]);

  async function loadMoreRepos() {
    if (view.kind !== "ready" || !view.hasNext || busy) {
      return;
    }
    const nextPage = view.page + 1;
    try {
      const page = await listRepos({
        baseUrl: apiBaseUrl,
        page: nextPage,
      });
      setView({
        kind: "ready",
        repos: [...view.repos, ...page.items],
        hasNext: page.has_next,
        page: nextPage,
      });
    } catch (error) {
      setView({ kind: "error", message: actionErrorMessage(error) });
    }
  }

  const canConfirm = Boolean(selectedOwner && selectedRepo) && !busy;

  return (
    <DialogFrame
      open={open}
      onClose={busy ? () => undefined : onCancel}
      labelledBy={titleId}
      panelClassName="kern-drive-picker"
    >
      <div className="kern-drive-picker-header">
        <h2 id={titleId}>Choose GitHub sync scope</h2>
        <p>Select one repository. Optionally add a Project for Issues.</p>
      </div>

      {notice ? (
        <div
          className="kern-settings-callout kern-settings-callout--error"
          role="alert"
        >
          <p>{notice}</p>
        </div>
      ) : null}

      {selectionLoading || view.kind === "loading" ? (
        <div className="kern-drive-picker-loading">
          <Loader label="Loading repositories" size="sm" />
        </div>
      ) : view.kind === "error" ? (
        <div
          className="kern-settings-callout kern-settings-callout--error"
          role="alert"
        >
          <p>{view.message}</p>
        </div>
      ) : (
        <div className="kern-drive-picker-body">
          <fieldset className="kern-drive-picker-list" disabled={busy}>
            <legend className="visually-hidden">Repositories</legend>
            {view.repos.length === 0 ? (
              <p>No repositories are visible to this GitHub account.</p>
            ) : (
              view.repos.map((repo) => {
                const selected =
                  selectedOwner === repo.owner && selectedRepo === repo.name;
                return (
                  <label key={repo.full_name} className="kern-drive-picker-row">
                    <input
                      type="radio"
                      name="github-repo"
                      checked={selected}
                      onChange={() => {
                        setSelectedOwner(repo.owner);
                        setSelectedRepo(repo.name);
                        setSelectedProjectOwner(null);
                        setSelectedProjectNumber(null);
                      }}
                    />
                    <span>
                      {repo.full_name}
                      {repo.private ? " (private)" : ""}
                    </span>
                  </label>
                );
              })
            )}
          </fieldset>
          {view.hasNext ? (
            <Button
              type="button"
              variant="ghost"
              disabled={busy}
              onClick={() => void loadMoreRepos()}
            >
              Load more repositories
            </Button>
          ) : null}

          {selectedOwner ? (
            <div className="kern-drive-picker-selection">
              <h3>Project (optional)</h3>
              {projectsLoading ? (
                <Loader label="Loading projects" size="sm" />
              ) : projectsError ? (
                <div
                  className="kern-settings-callout kern-settings-callout--warn"
                  role="status"
                >
                  <p>{projectsError}</p>
                </div>
              ) : (
                <fieldset className="kern-drive-picker-list" disabled={busy}>
                  <legend className="visually-hidden">Projects</legend>
                  <label className="kern-drive-picker-row">
                    <input
                      type="radio"
                      name="github-project"
                      checked={selectedProjectNumber == null}
                      onChange={() => {
                        setSelectedProjectOwner(null);
                        setSelectedProjectNumber(null);
                      }}
                    />
                    <span>No project (repository files only)</span>
                  </label>
                  {projects.map((project) => (
                    <label
                      key={`${project.owner_login}-${project.number}`}
                      className="kern-drive-picker-row"
                    >
                      <input
                        type="radio"
                        name="github-project"
                        checked={
                          selectedProjectOwner === project.owner_login &&
                          selectedProjectNumber === project.number
                        }
                        onChange={() => {
                          setSelectedProjectOwner(project.owner_login);
                          setSelectedProjectNumber(project.number);
                        }}
                      />
                      <span>
                        #{project.number} {project.title}
                      </span>
                    </label>
                  ))}
                </fieldset>
              )}
            </div>
          ) : null}
        </div>
      )}

      <div className="kern-drive-picker-actions">
        <Button
          type="button"
          variant="ghost"
          disabled={busy}
          onClick={onCancel}
        >
          Cancel
        </Button>
        <Button
          type="button"
          disabled={!canConfirm}
          onClick={() => {
            if (!selectedOwner || !selectedRepo) {
              return;
            }
            onConfirm({
              owner: selectedOwner,
              repo: selectedRepo,
              project_owner: selectedProjectOwner,
              project_number: selectedProjectNumber,
            });
          }}
        >
          {busy ? "Saving…" : "Save and sync"}
        </Button>
      </div>
    </DialogFrame>
  );
}
