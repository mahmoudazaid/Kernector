"""Pack-agnostic Streamlit entry for projected composition tool-run views.

``app.py`` imports this helper by a generic name so it never names pack
renderers or pack tool identifiers. Typed views arrive from the composition
side path / session — never by parsing ``AskResponse.tool_outputs``.
"""

from __future__ import annotations

from composition.software_delivery_tools import SoftwareDeliveryRunView
from presentation.streamlit.tool_run_panel import render_software_delivery_tool_results


def render_projected_results(view: SoftwareDeliveryRunView | None) -> None:
    """Render projected Software Delivery panels when a typed view is present."""
    if view is None:
        return
    render_software_delivery_tool_results(view)
