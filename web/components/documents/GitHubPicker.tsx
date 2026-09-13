"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";
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
  accountLogin?: string | null;
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

function CloseGlyph() {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <path
        d="M5 5l10 10M15 5 5 15"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
    </svg>
  );
}

function RepoGlyph() {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <path
        d="M6.2 3.5h7.6c.9 0 1.7.7 1.7 1.6v9.8c0 .9-.8 1.6-1.7 1.6H6.2c-.9 0-1.7-.7-1.7-1.6V5.1c0-.9.8-1.6 1.7-1.6Z"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      <path
        d="M8 7h4M8 10h4M8 13h2.5"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

function ProjectGlyph() {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <path
        d="M4 5.5h12M4 10h12M4 14.5h8"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

function sourceCountLabel(count: number): string {
  if (count === 1) {
    return "1 source selected";
  }
  return `${count} sources selected`;
}

export function GitHubPicker({
  open,
  apiBaseUrl,
  accountLogin = null,
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
  const descriptionId = useId();
  const repoSearchId = useId();
  const projectSearchId = useId();
  const searchRef = useRef<HTMLInputElement>(null);
  const [view, setView] = useState<BrowseView>({ kind: "loading" });
  const [repoSearch, setRepoSearch] = useState("");
  const [projectSearch, setProjectSearch] = useState("");
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

  const projectListOwner =
    accountLogin?.trim() ||
    initialSelection.project_owner?.trim() ||
    selectedOwner?.trim() ||
    null;

  useEffect(() => {
    if (!open) {
      return;
    }
    setRepoSearch("");
    setProjectSearch("");
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
    if (!open || !projectListOwner) {
      setProjects([]);
      setProjectsError(null);
      setProjectsLoading(false);
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
          ownerLogin: projectListOwner,
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
  }, [open, apiBaseUrl, listProjects, projectListOwner]);

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
      if (!isAbortError(error)) {
        setView({ kind: "error", message: actionErrorMessage(error) });
      }
    }
  }

  const repoQuery = repoSearch.trim().toLowerCase();
  const filteredRepos = useMemo(() => {
    if (view.kind !== "ready") {
      return [];
    }
    if (!repoQuery) {
      return view.repos;
    }
    return view.repos.filter((repo) =>
      repo.full_name.toLowerCase().includes(repoQuery),
    );
  }, [view, repoQuery]);

  const projectQuery = projectSearch.trim().toLowerCase();
  const filteredProjects = useMemo(() => {
    if (!projectQuery) {
      return projects;
    }
    return projects.filter((project) => {
      const haystack =
        `${project.number} ${project.title} ${project.owner_login}`.toLowerCase();
      return haystack.includes(projectQuery);
    });
  }, [projects, projectQuery]);

  const listLoading = view.kind === "loading" || selectionLoading;
  const canConfirm = Boolean(selectedOwner && selectedRepo) && !busy;
  const selectedKey =
    selectedOwner && selectedRepo ? `${selectedOwner}/${selectedRepo}` : null;
  const hasProject =
    selectedProjectOwner != null && selectedProjectNumber != null;
  const selectedCount = (selectedKey ? 1 : 0) + (hasProject ? 1 : 0);
  const selectionUnchanged =
    selectedOwner === initialSelection.owner &&
    selectedRepo === initialSelection.repo &&
    selectedProjectOwner === initialSelection.project_owner &&
    selectedProjectNumber === initialSelection.project_number;

  return (
    <DialogFrame
      open={open}
      titleId={titleId}
      descriptionId={descriptionId}
      panelClassName="kern-picker-dialog kern-github-sources-dialog"
      initialFocusRef={searchRef}
      onDismiss={onCancel}
    >
      <div className="kern-picker-head">
        <div className="kern-picker-title-row">
          <div>
            <h2 id={titleId} className="kern-dialog-title">
              Choose GitHub sources
            </h2>
            <p id={descriptionId} className="kern-dialog-body">
              Pick one repository. Optionally add one Project for Issues —
              Projects are independent of the repository.
            </p>
          </div>
          <Button
            variant="ghost"
            className="kern-picker-close"
            aria-label="Close"
            onClick={onCancel}
          >
            <CloseGlyph />
          </Button>
        </div>
      </div>

      {notice ? (
        <div
          className="kern-settings-callout kern-settings-callout--error"
          role="alert"
        >
          <p>{notice}</p>
        </div>
      ) : null}

      <div className="kern-github-sources-panels">
        <section
          className="kern-github-source-panel"
          aria-labelledby="github-repo-panel-title"
        >
          <div className="kern-github-source-panel-head">
            <h3 id="github-repo-panel-title" className="kern-picker-crumbs">
              <strong>Repository code</strong>
              <span>Required · exactly one</span>
            </h3>
            <div className="kern-picker-search">
              <label htmlFor={repoSearchId} className="visually-hidden">
                Search repositories
              </label>
              <input
                ref={searchRef}
                id={repoSearchId}
                type="search"
                className="kern-settings-input"
                placeholder="Search repositories"
                value={repoSearch}
                onChange={(event) => setRepoSearch(event.target.value)}
                autoComplete="off"
              />
            </div>
          </div>
          <div
            className={
              listLoading ? "kern-picker-list is-loading" : "kern-picker-list"
            }
            role="radiogroup"
            aria-label="Repository code"
          >
            {listLoading ? (
              <div className="kern-picker-loading">
                <Loader label="Loading repositories" />
              </div>
            ) : null}
            {view.kind === "error" && !selectionLoading ? (
              <div
                className="kern-settings-callout kern-settings-callout--error"
                role="status"
              >
                <p>{view.message}</p>
              </div>
            ) : null}
            {view.kind === "ready" &&
            !selectionLoading &&
            filteredRepos.length === 0 ? (
              <p role="status">
                {repoQuery
                  ? "No matching repositories."
                  : "No repositories are available for this account."}
              </p>
            ) : null}
            {view.kind === "ready" && !selectionLoading
              ? filteredRepos.map((repo) => {
                  const checked = selectedKey === repo.full_name;
                  return (
                    <div
                      className={
                        checked
                          ? "kern-drive-item is-checked"
                          : "kern-drive-item"
                      }
                      key={repo.full_name}
                    >
                      <label className="kern-drive-item-select">
                        <input
                          type="radio"
                          name="github-repo"
                          checked={checked}
                          disabled={busy}
                          onChange={() => {
                            setSelectedOwner(repo.owner);
                            setSelectedRepo(repo.name);
                          }}
                        />
                        <span className="kern-drive-item-icon">
                          <RepoGlyph />
                        </span>
                        <span className="kern-drive-item-copy">
                          <strong>{repo.full_name}</strong>
                          <span className="kern-drive-item-meta">
                            {repo.private
                              ? "Private repository"
                              : "Public repository"}
                          </span>
                        </span>
                      </label>
                    </div>
                  );
                })
              : null}
            {view.kind === "ready" &&
            view.hasNext &&
            !selectionLoading &&
            !repoQuery ? (
              <Button
                variant="secondary"
                disabled={busy}
                onClick={() => void loadMoreRepos()}
              >
                Load more
              </Button>
            ) : null}
          </div>
        </section>

        <section
          className="kern-github-source-panel"
          aria-labelledby="github-project-panel-title"
        >
          <div className="kern-github-source-panel-head">
            <h3 id="github-project-panel-title" className="kern-picker-crumbs">
              <strong>Project issues</strong>
              <span>Optional · zero or one</span>
            </h3>
            <div className="kern-picker-search">
              <label htmlFor={projectSearchId} className="visually-hidden">
                Search projects
              </label>
              <input
                id={projectSearchId}
                type="search"
                className="kern-settings-input"
                placeholder="Search projects"
                value={projectSearch}
                onChange={(event) => setProjectSearch(event.target.value)}
                autoComplete="off"
                disabled={!projectListOwner || busy}
              />
            </div>
          </div>
          <div
            className={
              projectsLoading
                ? "kern-picker-list is-loading"
                : "kern-picker-list"
            }
            role="radiogroup"
            aria-label="Project issues"
          >
            {projectsLoading ? (
              <div className="kern-picker-loading">
                <Loader label="Loading projects" />
              </div>
            ) : null}
            {!projectListOwner && !projectsLoading ? (
              <p role="status">Connect a GitHub account to list Projects.</p>
            ) : null}
            {projectsError && !projectsLoading ? (
              <div
                className="kern-settings-callout kern-settings-callout--warn"
                role="status"
              >
                <p>{projectsError}</p>
              </div>
            ) : null}
            {!projectsLoading &&
            projectListOwner &&
            !projectsError &&
            filteredProjects.length === 0 ? (
              <p role="status">
                {projectQuery
                  ? "No matching projects."
                  : "No Projects are available for this account."}
              </p>
            ) : null}
            {!projectsLoading
              ? filteredProjects.map((project) => {
                  const checked =
                    selectedProjectOwner === project.owner_login &&
                    selectedProjectNumber === project.number;
                  return (
                    <div
                      className={
                        checked
                          ? "kern-drive-item is-checked"
                          : "kern-drive-item"
                      }
                      key={`${project.owner_login}-${project.number}`}
                    >
                      <label className="kern-drive-item-select">
                        <input
                          type="radio"
                          name="github-project"
                          checked={checked}
                          disabled={busy}
                          onChange={() => {
                            setSelectedProjectOwner(project.owner_login);
                            setSelectedProjectNumber(project.number);
                          }}
                          onClick={() => {
                            if (!checked || busy) {
                              return;
                            }
                            setSelectedProjectOwner(null);
                            setSelectedProjectNumber(null);
                          }}
                        />
                        <span className="kern-drive-item-icon">
                          <ProjectGlyph />
                        </span>
                        <span className="kern-drive-item-copy">
                          <strong>
                            #{project.number} {project.title}
                          </strong>
                          <span className="kern-drive-item-meta">
                            {project.owner_login}
                          </span>
                        </span>
                      </label>
                    </div>
                  );
                })
              : null}
          </div>
        </section>
      </div>

      <div className="kern-picker-foot">
        <span aria-live="polite">{sourceCountLabel(selectedCount)}</span>
        <div className="kern-dialog-actions">
          <Button variant="secondary" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
          <Button
            disabled={!canConfirm || selectionLoading || selectionUnchanged}
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
            Save
          </Button>
        </div>
      </div>
    </DialogFrame>
  );
}
