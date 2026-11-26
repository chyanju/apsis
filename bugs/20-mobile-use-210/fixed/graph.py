# Derived from mobile-use (github.com/minitap-ai/mobile-use, Apache-2.0) and modified; license text in LICENSE.
"""The mobile-use graph of bugs/19-mobile-use-208/fixed with the summarizer of PR #211, which returns the removals of
every overflow message after its loop."""

import asyncio
import importlib.util
from pathlib import Path

from langchain_core.messages import HumanMessage, RemoveMessage, ToolMessage


def _workflow():
    spec = importlib.util.spec_from_file_location(
        "mobile_use_workflow", Path(__file__).resolve().parents[2] / "19-mobile-use-208" / "fixed" / "graph.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


workflow = _workflow()


# minitap/mobile_use/agents/summarizer/summarizer.py


class SummarizerNode:
    def __init__(self, ctx):
        self.ctx = ctx

    async def __call__(self, state):
        if len(state.messages) <= workflow.MAX_MESSAGES_IN_HISTORY:
            return {}

        nb_removal_candidates = len(state.messages) - workflow.MAX_MESSAGES_IN_HISTORY

        remove_messages = []
        start_removal = False

        for msg in reversed(state.messages[:nb_removal_candidates]):
            if isinstance(msg, ToolMessage | HumanMessage):
                start_removal = True
            if start_removal and msg.id:
                remove_messages.append(RemoveMessage(id=msg.id))

        return await state.asanitize_update(
            ctx=self.ctx,
            update={
                "messages": remove_messages,
            },
        )


workflow.SummarizerNode = SummarizerNode
graph = asyncio.run(workflow.get_graph(workflow.MobileUseContext()))
