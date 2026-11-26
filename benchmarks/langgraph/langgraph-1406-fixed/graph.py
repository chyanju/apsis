import operator
from typing import Annotated, TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.constants import Send


class State(TypedDict):
    items: list[str]
    result: Annotated[list[str], operator.add]


def fan_out(state: State):
    return [Send("worker", {"item": s}) for s in state["items"]]


def worker(state: dict) -> dict:
    return {"result": [state["item"] + "!"]}


def collect(state: State) -> dict:
    return {}


def build():
    g = StateGraph(State)
    g.add_node("worker", worker)
    g.add_node("collect", collect)
    g.add_conditional_edges(START, fan_out, ["worker"])
    g.add_edge("worker", "collect")
    g.add_edge("collect", END)
    return g.compile()


graph = build()
