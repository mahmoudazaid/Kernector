"""Registration entrypoint for the Software Delivery domain tool pack."""

from collections.abc import Sequence

from packs.software_delivery.risk_score_tool import RiskScoreTool


def build_tools() -> Sequence[RiskScoreTool]:
    """Return tools contributed by this pack."""
    return (RiskScoreTool(),)
