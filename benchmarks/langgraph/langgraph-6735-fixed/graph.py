import operator
from typing import Annotated, TypedDict

from langgraph.graph import StateGraph, START, END


class State(TypedDict):
    messages: Annotated[list[str], operator.add]
    count: int


def process(state: State) -> dict:
    return {"messages": ["processed"]}


def orphan_node(state: State) -> dict:
    return {"messages": ["orphan was here"]}


def dead_end(state: State) -> dict:
    return {"messages": ["dead_end_result"]}


def island_a(state: State) -> dict:
    return {"count": state["count"] + 10}


def island_b(state: State) -> dict:
    return {"count": state["count"] + 20}


def build():
    g = StateGraph(State)
    g.add_node("process", process)
    g.add_node("orphan", orphan_node)
    g.add_node("dead_end", dead_end)
    g.add_node("island_a", island_a)
    g.add_node("island_b", island_b)

    g.add_edge(START, "process")
    g.add_edge("process", "orphan")
    g.add_edge("orphan", END)

    g.add_edge(START, "dead_end")
    g.add_edge("dead_end", END)

    g.add_edge(START, "island_a")
    g.add_edge("island_a", "island_b")
    g.add_edge("island_b", END)

    return g.compile()


graph = build()
