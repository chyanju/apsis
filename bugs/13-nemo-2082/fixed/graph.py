# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# Derived from NeMo Agent Toolkit (github.com/NVIDIA/NeMo-Agent-Toolkit) and modified; license text in LICENSE.

import asyncio

from langchain_core.messages.base import BaseMessage
from langchain_core.messages.human import HumanMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END
from langgraph.graph import StateGraph
from pydantic import BaseModel
from pydantic import Field


class RouterAgentGraphState(BaseModel):
    """State schema for the Router Agent Graph."""
    messages: list[BaseMessage] = Field(default_factory=list)
    forward_message: BaseMessage = Field(default_factory=lambda: HumanMessage(content=""))
    chosen_branch: str = Field(default="")


class RouterAgentGraph:
    """Routes a request to one of the configured branches and executes only that branch."""

    def __init__(self, branches: list[BaseTool]):
        self._branches = branches
        self._branches_dict = {branch.name: branch for branch in branches}
        self.graph = None

    def _get_branch(self, branch_name: str) -> BaseTool | None:
        return self._branches_dict.get(branch_name, None)

    async def agent_node(self, state: RouterAgentGraphState):
        state.chosen_branch = ""
        return state

    async def branch_node(self, state: RouterAgentGraphState):
        branch = self._get_branch(state.chosen_branch)
        if branch is None:
            return state
        state.messages += [HumanMessage(content="")]
        return state

    async def _build_graph(self, state_schema):
        graph = StateGraph(state_schema)
        graph.add_node("agent", self.agent_node)
        graph.add_node("branch", self.branch_node)
        graph.add_edge("agent", "branch")
        graph.add_edge("branch", END)
        graph.set_entry_point("agent")

        self.graph = graph.compile()

        return self.graph

    async def build_graph(self):
        await self._build_graph(state_schema=RouterAgentGraphState)
        return self.graph


graph = asyncio.run(RouterAgentGraph(branches=[]).build_graph())
