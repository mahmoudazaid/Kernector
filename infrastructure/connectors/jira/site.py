"""Selected Jira instance identity (Cloud site or Data Center server)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class JiraSite:
    """One Jira instance the connector reads.

    ``cloud_id`` holds the stable instance identity used in source ids: the
    Atlassian cloud id for Jira Cloud, or the server id for Data Center. Prefer
    :attr:`instance_id` in provider-neutral code. ``site_url`` is the canonical
    ``https://<host>[/<context>]`` used only for browse URLs.
    """

    cloud_id: str
    site_url: str
    name: str

    @property
    def instance_id(self) -> str:
        return self.cloud_id

    def browse_url(self, issue_key: str) -> str:
        return f"{self.site_url}/browse/{issue_key}"
