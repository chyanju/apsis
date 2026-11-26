# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# Derived from NeMo Agent Toolkit (github.com/NVIDIA/NeMo-Agent-Toolkit) and modified; license text in LICENSE.

from typing import TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph import END
from langgraph.graph import StateGraph


class AgentState(TypedDict):
    input: str
    chat_history: list[BaseMessage] | None
    chosen_worker_agent: str | None
    final_output: str | None


async def supervisor(state: AgentState):
    query = state["input"]
    chosen_agent = "General"

    return {'input': query, "chosen_worker_agent": chosen_agent, "chat_history": []}


async def router(state: AgentState):
    status = list(state.keys())
    if 'final_output' in status:
        route_to = "end"
    elif 'chosen_worker_agent' not in status:
        route_to = "supevisor"
    elif 'chosen_worker_agent' in status:
        route_to = "workers"
    else:
        route_to = "end"
    return route_to


async def workers(state: AgentState):
    query = state["input"]
    worker_choice = state["chosen_worker_agent"]
    output = ""

    return {'input': query, "chosen_worker_agent": worker_choice, "chat_history": [], "final_output": output}


workflow = StateGraph(AgentState)
workflow.add_node("supervisor", supervisor)
workflow.set_entry_point("supervisor")
workflow.add_node("workers", workers)
workflow.add_conditional_edges(
    "supervisor",
    router,
    {
        "workers": "workers", "end": END
    },
)
workflow.add_edge("supervisor", "workers")
workflow.add_edge("workers", END)
graph = workflow.compile()
