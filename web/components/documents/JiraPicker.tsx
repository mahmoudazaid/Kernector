"use client";

import { useEffect, useId, useState } from "react";
import { Button } from "@/components/ui/Button";
import { DialogFrame } from "@/components/ui/DialogFrame";
import { Loader } from "@/components/ui/Loader";
import { ApiError, isAbortError } from "@/lib/api/errors";
import {
  listJiraProjects,
  listJiraSites,
  type JiraProjectItemResponse,
  type JiraProjectPageResponse,
  type JiraSiteListResponse,
  type JiraSiteResponse,
  type ListJiraProjectsOptions,
  type ListJiraSitesOptions,
} from "@/lib/api/connectors";

export type JiraPickerProps = {
  open: boolean;
  apiBaseUrl: string;
  site: JiraSiteResponse | null;
  initialProjectKeys: string[];
  busy?: boolean;
  /** Data Center has one configured server: no site step, projects list directly. */
  dataCenter?: boolean;
  listSites?: (options: ListJiraSitesOptions) => Promise<JiraSiteListResponse>;
  listProjects?: (
    options: ListJiraProjectsOptions,
  ) => Promise<JiraProjectPageResponse>;
  onSelectSite: (cloudId: string) => void;
  onConfirm: (projectKeys: string[]) => void;
  onCancel: () => void;
  notice?: string | null;
};

type SitesView =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; sites: JiraSiteResponse[] };

type ProjectsView =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | {
      kind: "ready";
      projects: JiraProjectItemResponse[];
      nextStartAt: number | null;
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

function projectCountLabel(count: number): string {
  if (count === 1) {
    return "1 project selected";
  }
  return `${count} projects selected`;
}

function sameKeys(left: string[], right: string[]): boolean {
  if (left.length !== right.length) {
    return false;
  }
  const rightSet = new Set(right);
  return left.every((key) => rightSet.has(key));
}

export function JiraPicker({
  open,
  apiBaseUrl,
  site,
  initialProjectKeys,
  busy = false,
  dataCenter = false,
  listSites = listJiraSites,
  listProjects = listJiraProjects,
  onSelectSite,
  onConfirm,
  onCancel,
  notice = null,
}: JiraPickerProps) {
  const titleId = useId();
  const descriptionId = useId();
  const [step, setStep] = useState<"site" | "projects">(
    site || dataCenter ? "projects" : "site",
  );
  const [sitesView, setSitesView] = useState<SitesView>({ kind: "loading" });
  const [projectsView, setProjectsView] = useState<ProjectsView>({
    kind: "loading",
  });
  const [chosenSite, setChosenSite] = useState<string | null>(
    site?.cloud_id ?? null,
  );
  const [selectedKeys, setSelectedKeys] = useState<string[]>(initialProjectKeys);

  const siteId = site?.cloud_id ?? null;
  const canListProjects = dataCenter || siteId !== null;

  useEffect(() => {
    if (!open) {
      return;
    }
    setStep(siteId || dataCenter ? "projects" : "site");
    setChosenSite(siteId);
    setSelectedKeys(initialProjectKeys);
  }, [open, siteId, dataCenter, initialProjectKeys]);

  useEffect(() => {
    if (!open || step !== "site") {
      return;
    }
    let ignore = false;
    const controller = new AbortController();
    setSitesView({ kind: "loading" });
    void (async () => {
      try {
        const page = await listSites({
          baseUrl: apiBaseUrl,
          signal: controller.signal,
        });
        if (!ignore) {
          setSitesView({ kind: "ready", sites: page.items });
        }
      } catch (error) {
        if (!ignore && !isAbortError(error)) {
          setSitesView({ kind: "error", message: actionErrorMessage(error) });
        }
      }
    })();
    return () => {
      ignore = true;
      controller.abort();
    };
  }, [open, step, apiBaseUrl, listSites]);

  useEffect(() => {
    if (!open || step !== "projects" || !canListProjects) {
      return;
    }
    let ignore = false;
    const controller = new AbortController();
    setProjectsView({ kind: "loading" });
    void (async () => {
      try {
        const page = await listProjects({
          baseUrl: apiBaseUrl,
          startAt: 0,
          signal: controller.signal,
        });
        if (!ignore) {
          setProjectsView({
            kind: "ready",
            projects: page.items,
            nextStartAt: page.next_start_at ?? null,
          });
        }
      } catch (error) {
        if (!ignore && !isAbortError(error)) {
          setProjectsView({ kind: "error", message: actionErrorMessage(error) });
        }
      }
    })();
    return () => {
      ignore = true;
      controller.abort();
    };
  }, [open, step, canListProjects, apiBaseUrl, listProjects]);

  async function loadMoreProjects() {
    if (
      projectsView.kind !== "ready" ||
      projectsView.nextStartAt === null ||
      busy
    ) {
      return;
    }
    try {
      const page = await listProjects({
        baseUrl: apiBaseUrl,
        startAt: projectsView.nextStartAt,
      });
      setProjectsView({
        kind: "ready",
        projects: [...projectsView.projects, ...page.items],
        nextStartAt: page.next_start_at ?? null,
      });
    } catch (error) {
      if (!isAbortError(error)) {
        setProjectsView({ kind: "error", message: actionErrorMessage(error) });
      }
    }
  }

  function toggleKey(key: string) {
    setSelectedKeys((current) =>
      current.includes(key)
        ? current.filter((item) => item !== key)
        : [...current, key],
    );
  }

  const siteStep = step === "site";

  return (
    <DialogFrame
      open={open}
      titleId={titleId}
      descriptionId={descriptionId}
      panelClassName="kern-picker-dialog"
      onDismiss={onCancel}
    >
      <div className="kern-picker-head">
        <div className="kern-picker-title-row">
          <div>
            <h2 id={titleId} className="kern-dialog-title">
              {siteStep ? "Choose a Jira site" : "Choose Jira projects"}
            </h2>
            <p id={descriptionId} className="kern-dialog-body">
              {siteStep
                ? "This Atlassian account can read more than one Jira Cloud site. Pick one."
                : `Issues from the selected projects on ${site?.name ?? (dataCenter ? "your Jira Data Center" : "this site")} sync into the Hub.`}
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

      {siteStep ? (
        <div
          className={
            sitesView.kind === "loading"
              ? "kern-picker-list is-loading"
              : "kern-picker-list"
          }
          role="radiogroup"
          aria-label="Jira sites"
        >
          {sitesView.kind === "loading" ? (
            <div className="kern-picker-loading">
              <Loader label="Loading Jira sites" />
            </div>
          ) : null}
          {sitesView.kind === "error" ? (
            <div
              className="kern-settings-callout kern-settings-callout--error"
              role="status"
            >
              <p>{sitesView.message}</p>
            </div>
          ) : null}
          {sitesView.kind === "ready" && sitesView.sites.length === 0 ? (
            <p role="status">No Jira Cloud sites are available for this account.</p>
          ) : null}
          {sitesView.kind === "ready"
            ? sitesView.sites.map((item) => {
                const cloudId = item.cloud_id;
                const checked = chosenSite === cloudId;
                return (
                  <div
                    className={
                      checked ? "kern-drive-item is-checked" : "kern-drive-item"
                    }
                    key={cloudId}
                  >
                    <label className="kern-drive-item-select">
                      <input
                        type="radio"
                        name="jira-site"
                        checked={checked}
                        disabled={busy}
                        onChange={() => setChosenSite(cloudId)}
                      />
                      <span className="kern-drive-item-copy">
                        <strong>{item.name}</strong>
                        <span className="kern-drive-item-meta">{item.url}</span>
                      </span>
                    </label>
                  </div>
                );
              })
            : null}
        </div>
      ) : (
        <div
          className={
            projectsView.kind === "loading"
              ? "kern-picker-list is-loading"
              : "kern-picker-list"
          }
          aria-label="Jira projects"
          role="group"
        >
          {projectsView.kind === "loading" ? (
            <div className="kern-picker-loading">
              <Loader label="Loading Jira projects" />
            </div>
          ) : null}
          {projectsView.kind === "error" ? (
            <div
              className="kern-settings-callout kern-settings-callout--error"
              role="status"
            >
              <p>{projectsView.message}</p>
            </div>
          ) : null}
          {projectsView.kind === "ready" && projectsView.projects.length === 0 ? (
            <p role="status">
              {dataCenter
                ? "No projects are visible to the configured token."
                : "No projects are visible on this site."}
            </p>
          ) : null}
          {projectsView.kind === "ready"
            ? projectsView.projects.map((project) => {
                const checked = selectedKeys.includes(project.key);
                return (
                  <div
                    className={
                      checked ? "kern-drive-item is-checked" : "kern-drive-item"
                    }
                    key={project.key}
                  >
                    <label className="kern-drive-item-select">
                      <input
                        type="checkbox"
                        checked={checked}
                        disabled={busy}
                        onChange={() => toggleKey(project.key)}
                      />
                      <span className="kern-drive-item-copy">
                        <strong>{project.name}</strong>
                        <span className="kern-drive-item-meta">{project.key}</span>
                      </span>
                    </label>
                  </div>
                );
              })
            : null}
          {projectsView.kind === "ready" && projectsView.nextStartAt !== null ? (
            <Button
              variant="secondary"
              disabled={busy}
              onClick={() => void loadMoreProjects()}
            >
              Load more
            </Button>
          ) : null}
        </div>
      )}

      <div className="kern-picker-foot">
        {siteStep ? (
          <span />
        ) : (
          <span aria-live="polite">{projectCountLabel(selectedKeys.length)}</span>
        )}
        <div className="kern-dialog-actions">
          {!siteStep && !dataCenter ? (
            <Button
              variant="ghost"
              disabled={busy}
              onClick={() => setStep("site")}
            >
              Change site
            </Button>
          ) : null}
          <Button variant="secondary" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
          {siteStep ? (
            <Button
              disabled={busy || !chosenSite}
              onClick={() => {
                if (!chosenSite) {
                  return;
                }
                if (chosenSite === siteId) {
                  setStep("projects");
                  return;
                }
                onSelectSite(chosenSite);
              }}
            >
              Use this site
            </Button>
          ) : (
            <Button
              disabled={busy || sameKeys(selectedKeys, initialProjectKeys)}
              onClick={() => onConfirm(selectedKeys)}
            >
              Save
            </Button>
          )}
        </div>
      </div>
    </DialogFrame>
  );
}
