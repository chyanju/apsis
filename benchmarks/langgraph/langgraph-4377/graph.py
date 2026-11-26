from typing import Literal

from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.prebuilt import ToolNode
from langgraph.types import Command


def add_numbers(a: int, b: int) -> int:
    """This helps in adding two numbers."""
    return a + b


def multiply_numbers(a: int, b: int) -> int:
    """This helps in multiplying two numbers."""
    return a * b


def supervisor_agent(
    state: MessagesState,
) -> Command[Literal["addition_expert_agent", "multiplication_expert_agent", END]]:
    agent_to_call = "addition_expert_agent"
    if agent_to_call in ("addition_expert_agent", "multiplication_expert_agent"):
        return Command(goto=agent_to_call, update={"messages": []})
    return {"messages": []}


def addition_expert_agent(state: MessagesState):
    def call_model(state: MessagesState):
        if getattr(state["messages"][-1], "tool_calls", None):
            return Command(goto="tool_node", update={"messages": []})
        return Command(update={"messages": []})

    tool_node = ToolNode([add_numbers])

    addition_expert_graph = StateGraph(MessagesState)
    addition_expert_graph.add_node("call_model", call_model)
    addition_expert_graph.add_node("tool_node", tool_node)
    addition_expert_graph.add_edge(START, "call_model")
    addition_expert_graph.add_edge("tool_node", "call_model")

    return addition_expert_graph.compile()


def multiplication_expert_agent(state: MessagesState):
    def call_model(state: MessagesState):
        if getattr(state["messages"][-1], "tool_calls", None):
            return Command(goto="tool_node", update={"messages": []})
        return Command(update={"messages": []})

    tool_node = ToolNode([multiply_numbers])

    multiplication_expert_graph = StateGraph(MessagesState)
    multiplication_expert_graph.add_node("call_model", call_model)
    multiplication_expert_graph.add_node("tool_node", tool_node)
    multiplication_expert_graph.add_edge(START, "call_model")
    multiplication_expert_graph.add_edge("tool_node", "call_model")

    return multiplication_expert_graph.compile()


def build():
    supervisor_graph = StateGraph(MessagesState)
    supervisor_graph.add_node("supervisor_node", supervisor_agent)
    supervisor_graph.add_node("addition_expert_agent", addition_expert_agent)
    supervisor_graph.add_node("multiplication_expert_agent", multiplication_expert_agent)
    supervisor_graph.add_edge(START, "supervisor_node")
    return supervisor_graph.compile()


graph = build()
