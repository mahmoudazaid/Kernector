"""Build the deployment-specific Xray importer from settings."""

from __future__ import annotations

from domain.ports import XrayTestImporter
from infrastructure.config import Settings
from infrastructure.connectors.xray.schema import XraySchemaCache

# Process-wide: keyed by (deployment, base_url, project_key), metadata only.
_SCHEMA_CACHE = XraySchemaCache()


def build_xray_importer(
    settings: Settings, *, cache: XraySchemaCache | None = None
) -> XrayTestImporter | None:
    """Return the configured importer, or ``None`` when Xray is disabled."""
    xray = settings.xray
    if not xray.configured or xray.project_key is None:
        return None
    schema_cache = cache or _SCHEMA_CACHE
    if xray.deployment == "server":
        from infrastructure.connectors.xray.server import XrayServerImporter

        jira = settings.jira_data_center
        if jira is None or jira.base_url is None or jira.token is None:
            return None
        return XrayServerImporter(
            base_url=jira.base_url,
            token=jira.token,
            project_key=xray.project_key,
            link_type=xray.link_type,
            cache=schema_cache,
        )
    from infrastructure.connectors.xray.cloud import XrayCloudImporter

    if xray.client_id is None or xray.client_secret is None:
        return None
    return XrayCloudImporter(
        base_url=xray.cloud_base_url,
        client_id=xray.client_id,
        client_secret=xray.client_secret,
        project_key=xray.project_key,
        link_type=xray.link_type,
        cache=schema_cache,
    )
