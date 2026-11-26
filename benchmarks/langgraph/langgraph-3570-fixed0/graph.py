import operator
import random
from typing import Annotated, Literal, TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.types import Command


class State(TypedDict):
    messages: Annotated[list, add_messages]
    personal_data: dict
    dialog_state: Annotated[list[str], operator.add]


def node_a_child(state: State) -> dict:
    return {"dialog_state": ["b_child_state"]}


def node_b_child(state: State) -> Command[Literal["node_c_child", "node_d_child"]]:
    value = random.choice([0, 1])
    return Command(goto="node_c_child" if value == 0 else "node_d_child")


def node_c_child(state: State) -> Command:
    return Command(graph=Command.PARENT, goto="node_sibling")


def node_d_child(state: State) -> dict:
    return {"dialog_state": ["d_child_state"]}


def build_subgraph():
    sub = StateGraph(State)
    sub.add_node("node_a_child", node_a_child)
    sub.add_edge(START, "node_a_child")
    sub.add_node("node_b_child", node_b_child)
    sub.add_edge("node_a_child", "node_b_child")
    sub.add_node("node_c_child", node_c_child)
    sub.add_edge("node_c_child", END)
    sub.add_node("node_d_child", node_d_child)
    sub.add_edge("node_d_child", END)
    return sub.compile()


def node_a_parent(state: State) -> dict:
    return {"dialog_state": ["a_parent_state"]}


def node_b_parent(state: State) -> dict:
    return {"dialog_state": ["pop"]}


def node_sibling(state: State) -> dict:
    return {"dialog_state": ["sibling"]}


def build():
    sub_graph = build_subgraph()

    main = StateGraph(State)
    main.add_node("node_a_parent", node_a_parent)
    main.add_edge(START, "node_a_parent")
    main.add_node("subgraph", sub_graph)
    main.add_edge("node_a_parent", "subgraph")
    main.add_node("node_b_parent", node_b_parent)
    main.add_edge("subgraph", "node_b_parent")
    main.add_edge("node_b_parent", END)
    main.add_node("node_sibling", node_sibling)
    main.add_edge("node_sibling", END)
    return main.compile(name="parent")


graph = build()
