from pydantic import BaseModel

from langgraph.graph import StateGraph, START, END
from langgraph.types import Command


class State(BaseModel):
    foo: str | None = None
    bar: str | None = None


def node_a(state: State):
    return Command(goto="node_b", update={"foo": "foo"})


def node_b(state: State):
    return Command(goto=END, update={"bar": "bar"})


def build():
    g = StateGraph(State)
    g.add_node(node_a)
    g.add_node(node_b)
    g.add_edge(START, "node_a")
    return g.compile()


graph = build()
