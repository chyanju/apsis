"""Classify a Flowise node's ``data`` block into an IR NodeKind."""
from __future__ import annotations

# AgentFlow `data.type` (or baseClasses[0]) -> IR NodeKind.
_TYPE_KIND = {
    "Start": "start",
    "Agent": "agent",
    "LLMNode": "agent",
    "LLM": "agent",
    "Tool": "tool",
    "Condition": "router",
    "ConditionAgent": "router",
    "Loop": "loop",
    "Iteration": "loop",
    "HumanInput": "human-input",
    "ExecuteFlow": "subflow",
    "DirectReply": "end",
    "End": "end",
}

# `data.name` -> IR NodeKind, for nodes without a `data.type`.
_NAME_KIND = {
    "startAgentflow": "start",
    "seqStart": "start",
    "seqEnd": "end",
    "seqAgent": "agent",
    "seqLLMNode": "agent",
    "llmAgentflow": "agent",
    "agentAgentflow": "agent",
    "conditionAgentAgentflow": "router",
    "conditionAgentflow": "router",
    "seqCondition": "router",
    "seqConditionAgent": "router",
    "ifElseFunction": "router",
    "loopAgentflow": "loop",
    "seqLoop": "loop",
    "iterationAgentflow": "loop",
    "humanInputAgentflow": "human-input",
    "executeFlowAgentflow": "subflow",
    "seqExecuteFlow": "subflow",
    "chatflowTool": "subflow",
    "directReplyAgentflow": "end",
    "toolAgentflow": "tool",
    "seqToolNode": "tool",
    "toolAgent": "agent",
    "supervisor": "agent",
    "worker": "agent",
}

# `data.name` values of tool components that carry no `data.type`.
_TOOL_NAMES = {"calculator", "serpAPI", "searchTool", "retrieverTool", "customTool",
               "customMCP", "braveSearchAPI", "requestsGet", "requestsPost"}


def _node_kind(data: dict) -> str:
    t = data.get("type")
    if not t:
        bc = data.get("baseClasses")
        if isinstance(bc, list) and bc:
            t = bc[0]
    if t in _TYPE_KIND:
        return _TYPE_KIND[t]
    name = data.get("name", "")
    if name in _NAME_KIND:
        return _NAME_KIND[name]
    if name in _TOOL_NAMES:
        return "tool"
    cat = data.get("category", "")
    if cat == "Tools":
        return "tool"
    if cat in ("Chat Models", "LLMs"):
        return "component"  # a model is a plain operator wired as a Model edge
    return "component"
