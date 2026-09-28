"""Selected Jira Cloud site identity."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class JiraSite:
    """One Jira Cloud site reachable through the Atlassian grant.

    ``cloud_id`` is the stable identity used for API routing and source ids;
    ``site_url`` is the canonical ``https://<host>`` used only for browse URLs.
    """

    cloud_id: str
    site_url: str
    name: str

    def browse_url(self, issue_key: str) -> str:
        return f"{self.site_url}/browse/{issue_key}"
