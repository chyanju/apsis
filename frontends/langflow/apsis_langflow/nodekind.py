"""Classify a langflow component into an IR ``NodeKind`` by the words of its class name and its output handles."""
from __future__ import annotations

import re

from .subflow import _referenced_flow_key

# Each hint is a run of whole words of the CamelCase class name, so OpenRouterComponent is no router.
_ROUTER_HINTS = (("conditional", "router"), ("if", "else"), ("switch", "case"))
_LOOP_HINTS = (("loop",),)
_AGENT_HINTS = (("agent",),)
_SUBFLOW_HINTS = (("run", "flow"), ("flow", "tool"), ("subflow",), ("sub", "flow"))
_HUMAN_HINTS = (("human", "input"), ("human", "in", "the", "loop"), ("request", "info"), ("ask",))

# Router branch outputs: each is emitted on only some runs.
_BRANCH_OUTPUTS = {"true_result", "false_result", "router_response", "default_result"}


def _words(class_name: str) -> list[str]:
    """``HumanInTheLoopComponent`` -> human, in, the, loop, component."""
    return [w.lower() for w in re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|[0-9]+", class_name or "")]


def _has(words: list[str], hints) -> bool:
    """Whether one of ``hints`` occurs as consecutive words of a class name."""
    return any(words[i:i + len(h)] == list(h) for h in hints for i in range(len(words) - len(h) + 1))


def _node_kind(comp_type: str, node_def: dict, node_data: dict) -> str:
    t = _words(comp_type)
    # a node that references another flow is a subflow, whatever its name
    if (
        _has(t, _SUBFLOW_HINTS)
        or "referenced_flow" in node_data
        or _referenced_flow_key(node_def, node_data) is not None
    ):
        return "subflow"
    # before the loop check: a router's branch outputs also carry ``allows_loop``
    if _has(t, _ROUTER_HINTS) or _has_branch_outputs(node_def):
        return "router"
    if _has(t, _HUMAN_HINTS):
        return "human-input"
    if _has(t, _LOOP_HINTS) or _has_loop_output(node_def):
        return "loop"
    if _has(t, _AGENT_HINTS):
        return "agent"
    return "component"


def _has_loop_output(node_def: dict) -> bool:
    return any(o.get("allows_loop") for o in node_def.get("outputs", []) if isinstance(o, dict))


def _has_branch_outputs(node_def: dict) -> bool:
    names = {o.get("name") for o in node_def.get("outputs", []) if isinstance(o, dict)}
    return "true_result" in names and "false_result" in names
