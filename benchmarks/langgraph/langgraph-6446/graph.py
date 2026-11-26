from typing import TypedDict

from langgraph.graph import StateGraph, START, END


class State(TypedDict):
    a: int
    b: str
    s1: int
    s2: int


def nodea(state: State) -> dict:
    return {"a": 1}


def subnode1(state: State) -> dict:
    return {"s1": 1}


def subnode2(state: State) -> dict:
    return {"s2": 1}


def nodeb(state: State) -> dict:
    return {"b": "from-nodeb"}


def build_subgraph():
    g = StateGraph(State)
    g.add_node("subnode1", subnode1)
    g.add_node("subnode2", subnode2)
    g.add_edge(START, "subnode1")
    g.add_edge(START, "subnode2")
    return g.compile()


subgraph = build_subgraph()


def build():
    g = StateGraph(State)
    g.add_node("nodea", nodea)
    g.add_node("subgraph", subgraph)
    g.add_node("nodeb", nodeb)
    g.add_edge(START, "nodea")
    g.add_edge("nodea", "nodeb")
    g.add_edge("nodea", "subgraph")
    g.add_edge("nodeb", END)
    g.add_edge("subgraph", END)
    return g.compile()


graph = build()
