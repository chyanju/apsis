from typing import TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, START, END
from langgraph.types import Command


class State(TypedDict):
    value: str


def sub_sub_child(state: State) -> Command:
    return Command(
        goto="sub_child_3",
        update={"value": "sub_sub_child -> sub_child_3"},
    )


def sub_child_3(state: State) -> dict:
    return {"value": "sub_child_3"}


def build_sub_sub_graph():
    g = StateGraph(State)
    g.add_node("sub_sub_child", sub_sub_child)
    g.add_node("sub_child_3", sub_child_3)
    g.add_edge(START, "sub_sub_child")
    g.add_edge("sub_child_3", END)
    return g.compile(name="sub_sub_graph", checkpointer=True)


sub_sub_graph = build_sub_sub_graph()


def sub_child_1(state: State) -> dict:
    return {"value": "sub_child_1"}


def build_sub_graph():
    g = StateGraph(State)
    g.add_node("sub_child_1", sub_child_1)
    g.add_node("sub_child_2", sub_sub_graph)
    g.add_edge(START, "sub_child_1")
    g.add_edge("sub_child_1", "sub_child_2")
    return g.compile(name="sub_graph", checkpointer=True)


sub_graph = build_sub_graph()


def child_1(state: State) -> dict:
    return {"value": "child_1"}


def build():
    g = StateGraph(State)
    g.add_node("child_1", child_1)
    g.add_node("child_2", sub_graph)
    g.add_edge(START, "child_1")
    g.add_edge("child_1", "child_2")
    return g.compile(name="main_graph", checkpointer=MemorySaver())


graph = build()
