# Derived from openagent (github.com/Haohao-end/openagent, MIT) and modified; license text in LICENSE.

from enum import Enum
from typing import Annotated, Any, Optional
from uuid import UUID

from langchain_core.runnables import RunnableConfig, RunnableSerializable
from langgraph.graph import StateGraph
from pydantic import BaseModel, Field
from typing_extensions import TypedDict


class NodeType(str, Enum):
    START = "start"
    TEMPLATE_TRANSFORM = "template_transform"
    IF_ELSE = "if_else"
    END = "end"


class BaseNodeData(BaseModel):
    id: UUID
    node_type: NodeType
    title: str = ""


class BaseEdgeData(BaseModel):
    id: UUID
    source: UUID
    source_type: NodeType
    target: UUID
    target_type: NodeType
    source_handle: Optional[str] = None
    target_handle: Optional[str] = None


class NodeResult(BaseModel):
    node_data: BaseNodeData
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)


def _process_dict(left: dict[str, Any] = None, right: dict[str, Any] = None) -> dict[str, Any]:
    left = left or {}
    right = right or {}
    return {**left, **right}


def _process_node_results(left: list[NodeResult] = None, right: list[NodeResult] = None) -> list[NodeResult]:
    left = left or []
    right = right or []
    return left + right


class WorkflowState(TypedDict):
    inputs: Annotated[dict[str, Any], _process_dict]
    outputs: Annotated[dict[str, Any], _process_dict]
    node_results: Annotated[list[NodeResult], _process_node_results]


class BaseNode(RunnableSerializable):
    node_data: BaseNodeData


class StartNode(BaseNode):
    def invoke(self, state: WorkflowState, config: Optional[RunnableConfig] = None) -> WorkflowState:
        return {"node_results": [NodeResult(node_data=self.node_data, outputs=state["inputs"])]}


class TemplateTransformNode(BaseNode):
    def invoke(self, state: WorkflowState, config: Optional[RunnableConfig] = None) -> WorkflowState:
        return {"node_results": [NodeResult(node_data=self.node_data, outputs={"output": ""})]}


class IfElseNode(BaseNode):
    def invoke(self, state: WorkflowState, config: Optional[RunnableConfig] = None) -> WorkflowState:
        condition_result = bool(state["inputs"])
        return {"node_results": [NodeResult(node_data=self.node_data, outputs={"result": condition_result})]}


class EndNode(BaseNode):
    def invoke(self, state: WorkflowState, config: Optional[RunnableConfig] = None) -> WorkflowState:
        outputs_dict = {}
        return {
            "outputs": outputs_dict,
            "node_results": [NodeResult(node_data=self.node_data, outputs=outputs_dict)],
        }


NodeClasses = {
    NodeType.START.value: StartNode,
    NodeType.END.value: EndNode,
    NodeType.TEMPLATE_TRANSFORM.value: TemplateTransformNode,
    NodeType.IF_ELSE.value: IfElseNode,
}


def build_workflow(nodes: list[BaseNodeData], edges: list[BaseEdgeData]):
    graph = StateGraph(WorkflowState)

    for node in nodes:
        node_flag = f"{node.node_type.value}_{node.id}"
        graph.add_node(node_flag, NodeClasses[node.node_type.value](node_data=node))

    parallel_edges = {}
    conditional_edges = {}
    start_node = ""
    end_node = ""

    for edge in edges:
        source_node = f"{edge.source_type.value}_{edge.source}"
        target_node = f"{edge.target_type.value}_{edge.target}"

        if edge.source_type == NodeType.IF_ELSE.value:
            if source_node not in conditional_edges:
                conditional_edges[source_node] = {}
            branch = edge.source_handle if edge.source_handle is not None else "true"
            conditional_edges[source_node][branch] = target_node
        else:
            if target_node not in parallel_edges:
                parallel_edges[target_node] = []
            parallel_edges[target_node].append(source_node)

        if edge.source_type == NodeType.START.value:
            start_node = source_node
        if edge.target_type == NodeType.END.value:
            end_node = target_node

    graph.set_entry_point(start_node)
    graph.set_finish_point(end_node)

    for target_node, source_nodes in parallel_edges.items():
        for source_node in source_nodes:
            graph.add_edge(source_node, target_node)

    for if_else_node, branches in conditional_edges.items():
        def create_condition_func(node_id):
            def condition_func(state: WorkflowState):
                for node_result in reversed(state.get("node_results", [])):
                    if f"{node_result.node_data.node_type}_{node_result.node_data.id}" == node_id:
                        result = node_result.outputs.get("result", True)
                        return "true" if result else "false"
                return "true"
            return condition_func

        graph.add_conditional_edges(
            if_else_node,
            create_condition_func(if_else_node),
            branches
        )

    return graph.compile()


# A workflow whose if_else node has only its `true` side connected.
START_ID, IF_ELSE_ID, TEMPLATE_ID, END_ID = (UUID(int=i) for i in range(1, 5))

nodes = [
    BaseNodeData(id=START_ID, node_type=NodeType.START),
    BaseNodeData(id=IF_ELSE_ID, node_type=NodeType.IF_ELSE),
    BaseNodeData(id=TEMPLATE_ID, node_type=NodeType.TEMPLATE_TRANSFORM),
    BaseNodeData(id=END_ID, node_type=NodeType.END),
]
edges = [
    BaseEdgeData(id=UUID(int=11), source=START_ID, source_type=NodeType.START,
                 target=IF_ELSE_ID, target_type=NodeType.IF_ELSE),
    BaseEdgeData(id=UUID(int=12), source=IF_ELSE_ID, source_type=NodeType.IF_ELSE,
                 target=TEMPLATE_ID, target_type=NodeType.TEMPLATE_TRANSFORM, source_handle="true"),
    BaseEdgeData(id=UUID(int=13), source=TEMPLATE_ID, source_type=NodeType.TEMPLATE_TRANSFORM,
                 target=END_ID, target_type=NodeType.END),
]

graph = build_workflow(nodes, edges)
