from typing import TypedDict

from langgraph.graph import StateGraph, START, END


class State(TypedDict):
    value: str


def node_a(state: State) -> dict:
    return {"value": "from-a"}


def node_b(state: State) -> dict:
    return {"value": "from-b"}


def join(state: State) -> dict:
    return {}


def build():
    g = StateGraph(State)
    g.add_node("a", node_a)
    g.add_node("b", node_b)
    g.add_node("join", join)
    g.add_edge(START, "a")
    g.add_edge(START, "b")
    g.add_edge("a", "join")
    g.add_edge("b", "join")
    g.add_edge("join", END)
    return g.compile()


graph = build()
