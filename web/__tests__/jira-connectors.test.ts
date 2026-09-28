import { describe, expect, it, vi } from "vitest";
import {
  CONNECTOR_SYNC_TIMEOUT_MS,
  disconnectJira,
  getJiraSelection,
  getJiraStatus,
  jiraOAuthStartUrl,
  listJiraProjects,
  listJiraSites,
  putJiraSelection,
  putJiraSite,
  syncJira,
} from "@/lib/api/connectors";

describe("Jira connectors API client", () => {
  it("builds the OAuth start URL", () => {
    expect(jiraOAuthStartUrl("http://localhost:8000/")).toBe(
      "http://localhost:8000/api/v1/connectors/jira/oauth/start",
    );
  });

  it("GETs status, sites, projects, and selection", async () => {
    const request = vi.fn().mockResolvedValue({});
    await getJiraStatus({ baseUrl: "http://api", request });
    await listJiraSites({ baseUrl: "http://api", request });
    await listJiraProjects({ baseUrl: "http://api", request, startAt: 50 });
    await getJiraSelection({ baseUrl: "http://api", request });

    const calls = request.mock.calls.map(([options]) => [options.method, options.path]);
    expect(calls).toEqual([
      ["GET", "/api/v1/connectors/jira"],
      ["GET", "/api/v1/connectors/jira/sites"],
      ["GET", "/api/v1/connectors/jira/projects?start_at=50"],
      ["GET", "/api/v1/connectors/jira/selection"],
    ]);
  });

  it("PUTs the site and project selection", async () => {
    const request = vi.fn().mockResolvedValue({});
    await putJiraSite({ baseUrl: "http://api", request, cloudId: "cloud-1" });
    await putJiraSelection({ baseUrl: "http://api", request, projectKeys: ["ENG"] });

    expect(request).toHaveBeenNthCalledWith(
      1,
      expect.objectContaining({
        path: "/api/v1/connectors/jira/site",
        method: "PUT",
        body: { cloud_id: "cloud-1" },
      }),
    );
    expect(request).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({
        path: "/api/v1/connectors/jira/selection",
        method: "PUT",
        body: { project_keys: ["ENG"] },
      }),
    );
  });

  it("POSTs sync with the long timeout and DELETEs disconnect", async () => {
    const request = vi.fn().mockResolvedValue(undefined);
    await syncJira({ baseUrl: "http://api", request });
    await disconnectJira({ baseUrl: "http://api", request });

    expect(request).toHaveBeenNthCalledWith(
      1,
      expect.objectContaining({
        path: "/api/v1/connectors/jira/sync",
        method: "POST",
        timeoutMs: CONNECTOR_SYNC_TIMEOUT_MS,
      }),
    );
    expect(request).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({ path: "/api/v1/connectors/jira", method: "DELETE" }),
    );
  });
});
