from typing_extensions import TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph


class SubGraphState(TypedDict, total=False):
    run_idx: int
    sub_counter: int


def subgraph_accumulator(state: SubGraphState) -> SubGraphState:
    sub_counter = state["sub_counter"] + 1 if "sub_counter" in state else 0
    return {"sub_counter": sub_counter}


sub_graph = (
    StateGraph(SubGraphState)
    .add_node(subgraph_accumulator)
    .add_edge(START, "subgraph_accumulator")
    .add_edge("subgraph_accumulator", END)
    .compile(name="sub")
)


class ParentGraphState(TypedDict, total=False):
    run_idx: int
    parent_counter: int
    sub_counter: int


def parent_graph_accumulator(state: ParentGraphState) -> ParentGraphState:
    parent_counter = state["parent_counter"] + 1 if "parent_counter" in state else 0
    return {"parent_counter": parent_counter}


def build():
    g = StateGraph(ParentGraphState)
    g.add_node(parent_graph_accumulator)
    g.add_node(sub_graph)
    g.add_edge(START, "parent_graph_accumulator")
    g.add_edge("parent_graph_accumulator", "sub")
    g.add_edge("sub", END)
    return g.compile(checkpointer=MemorySaver())


graph = build()
