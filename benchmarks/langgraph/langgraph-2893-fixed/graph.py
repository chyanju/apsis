from typing_extensions import TypedDict

from langgraph.graph import StateGraph, START, END


class OverallState(TypedDict):
    a: str


class Node1Output(TypedDict):
    private_data: str


class Node2Input(TypedDict):
    private_data: str


class Nodes:
    def node_1(self, state: OverallState) -> Node1Output:
        return {"private_data": "set by node_1"}

    def node_2(self, state: Node2Input) -> OverallState:
        return {"a": "set by node_2"}

    def node_3(self, state: OverallState) -> OverallState:
        return {"a": "set by node_3"}


def build():
    nodes = Nodes()
    builder = StateGraph(OverallState)
    builder.add_node("node_1", nodes.node_1)
    builder.add_node("node_2", nodes.node_2)
    builder.add_node("node_3", nodes.node_3)
    builder.add_edge(START, "node_1")
    builder.add_edge("node_1", "node_2")
    builder.add_edge("node_2", "node_3")
    builder.add_edge("node_3", END)
    return builder.compile()


graph = build()
