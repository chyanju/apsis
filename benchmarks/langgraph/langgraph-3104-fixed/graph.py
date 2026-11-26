from typing import Any

from pydantic import BaseModel

from langgraph.graph import StateGraph, START, END


class State(BaseModel):
    a: int


class NodeAOutput(BaseModel):
    private_a: int


class NodeBInput(State):
    private_a: int = 0
    private_b: int = 0


class NodeBOutput(BaseModel):
    private_b: int


class GraphState(BaseModel):
    a: int
    private_a: int = 0
    private_b: int = 0


def node_a(state: State) -> dict:
    return {"private_a": 1}


def node_b(state: NodeBInput) -> dict:
    return {"private_b": 2}


def node_b_edge(state: NodeBInput):
    return END if state.private_b == 2 else "node_a"


def build():
    g = StateGraph(GraphState)
    g.add_node("node_a", node_a)
    g.add_node("node_b", node_b)
    g.add_edge("node_a", "node_b")
    g.add_conditional_edges("node_b", node_b_edge)
    g.set_entry_point("node_a")
    return g.compile()


graph = build()
