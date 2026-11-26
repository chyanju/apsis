from typing_extensions import Annotated, TypedDict

from langgraph.graph import StateGraph, START, END


def unique_list_merge(a: list, b: list) -> list:
    return list(dict.fromkeys(a + b))


class OverallState(TypedDict):
    list_a: Annotated[list[str], unique_list_merge]


def node_1(state: OverallState) -> OverallState:
    return {"list_a": ["node_1"]}


def node_2(state: OverallState) -> OverallState:
    return {"list_a": ["node_2"]}


def sub_node_1(state: OverallState) -> OverallState:
    return {"list_a": ["sub_node_1"]}


def build():
    subgraph_builder = StateGraph(OverallState)
    subgraph_builder.add_node(sub_node_1)
    subgraph_builder.add_edge(START, sub_node_1.__name__)
    subgraph_builder.add_edge(sub_node_1.__name__, END)
    subgraph = subgraph_builder.compile(name="subgraph")

    builder = StateGraph(OverallState)
    builder.add_node(node_1)
    builder.add_node(node_2)
    builder.add_node(subgraph)
    builder.add_edge(START, node_1.__name__)
    builder.add_edge(node_1.__name__, node_2.__name__)
    builder.add_edge(node_2.__name__, subgraph.name)
    builder.add_edge(subgraph.name, END)
    return builder.compile(name="main_graph")


graph = build()
