import operator
from typing import Annotated, TypedDict

from langgraph.graph import StateGraph, START, END


class State(TypedDict):
    count_a: int
    count_b: Annotated[list[int], operator.add]
    count_b_true: bool
    count_ab_check: int


def entry(state: State) -> dict:
    return {}


def writer_b(state: State) -> dict:
    return {"count_a": state.get("count_a", 0) + 1}


def retry_c(state: State) -> dict:
    return {"count_b": [1],
            "count_ab_check": state.get("count_ab_check", 0) + 1,
            "count_b_true": False}


def retry_cond(state: State) -> str:
    return "next" if state.get("count_ab_check", 0) >= 3 else "retry"


def merge_d(state: State) -> dict:
    return {"count_b": [0]}


def build():
    g = StateGraph(State)
    g.add_node("a", entry)
    g.add_node("b", writer_b)
    g.add_node("c", retry_c)
    g.add_node("d", merge_d)
    g.add_edge(START, "a")
    g.add_edge("a", "b")
    g.add_edge("a", "c")
    g.add_edge("b", "d")
    g.add_conditional_edges("c", retry_cond, {"retry": "c", "next": "d"})
    g.add_edge("d", END)
    return g.compile()


graph = build()
