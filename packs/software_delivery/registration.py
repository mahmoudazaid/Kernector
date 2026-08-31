"""Registration entrypoint for the Software Delivery domain tool pack."""

from collections.abc import Sequence

from domain.ports import ChatModel, Tool
from packs.software_delivery.generate_test_cases_tool import GenerateTestCasesTool
from packs.software_delivery.risk_score_tool import RiskScoreTool


def build_tools(*, chat_model: ChatModel) -> Sequence[Tool]:
    """Return tools contributed by this pack."""
    return (RiskScoreTool(), GenerateTestCasesTool(chat_model))
