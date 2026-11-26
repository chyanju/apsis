import operator
from typing import Annotated, TypedDict

from langgraph.graph import StateGraph, START, END


class State(TypedDict):
    messages: Annotated[list[str], operator.add]


def node1(state: State) -> dict:
    return {"messages": ["from node1"]}


def node2(state: State) -> dict:
    return {"messages": ["from node2"]}


def node3(state: State) -> dict:
    return {"messages": ["from node3"]}


def node4(state: State) -> dict:
    return {"messages": ["from node4"]}


def node5(state: State) -> dict:
    return {"messages": ["from node5"]}


def route(state: State):
    if len(state["messages"]) % 2 == 0:
        return "node5"
    return "__end__"


def build():
    g = StateGraph(State)
    g.add_node("node1", node1)
    g.add_node("node2", node2)
    g.add_node("node3", node3)
    g.add_node("node4", node4)
    g.add_node("node5", node5)
    g.add_edge(START, "node1")
    g.add_edge("node1", "node2")
    g.add_edge("node2", "node3")
    g.add_edge("node3", "node4")
    g.add_edge("node5", "node4")
    g.add_conditional_edges("node4", route)
    return g.compile()


graph = build()
