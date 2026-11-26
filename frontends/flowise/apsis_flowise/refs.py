"""Flowise bindings by reference: shared instances, tool selections, sub-flows and loop targets."""
from __future__ import annotations

import re

# a model/prompt/tool instance bound by reference
_INSTANCE_REF = re.compile(r"\{\{\s*([A-Za-z_]\w*?)\.data\.instance\s*\}\}")
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F-]{4,}$")

# keys whose value is the UUID of a selected tool or config
_SELECTION_KEYS = ("selectedTool", "toolAgentflowSelectedTool", "agentSelectedTool")


def _iter_strings(v):
    if isinstance(v, str):
        yield v
    elif isinstance(v, dict):
        for x in v.values():
            yield from _iter_strings(x)
    elif isinstance(v, list):
        for x in v:
            yield from _iter_strings(x)


def _subflow_ref(data: dict) -> dict | None:
    """The ``subflow_ref`` of an Execute Flow node; the export has no port bindings, so they stay empty."""
    inputs = data.get("inputs") or {}
    child = inputs.get("executeFlowSelectedFlow") or inputs.get("selectedFlow")
    if isinstance(child, str) and child.strip():
        return {"workflow": child.strip(), "in_bindings": [], "out_bindings": []}
    return None


def _declared_targets(data: dict, id_set: set[str]) -> list[str]:
    """The node a Loop loops back to: ``loopBackToNode`` (AgentFlow, a node id) or ``loopToName`` (a name)."""
    inputs = data.get("inputs") or {}
    targets: list[str] = []
    lb = inputs.get("loopBackToNode")
    if isinstance(lb, str) and lb:
        nid = lb.split("-")[0]  # "startAgentflow_0-Start" -> node-id prefix
        targets.append(nid if nid in id_set else lb)
    name = inputs.get("loopToName")
    if isinstance(name, str) and name.strip():
        # target resolution also matches Node.name
        targets.append(name.strip())
    return targets


def _selected_tool_ids(data: dict):
    """The tool/config UUIDs an Agent or Tool node selects, anywhere in its inputs."""
    inputs = data.get("inputs") or {}

    def walk(v):
        if isinstance(v, dict):
            for k, val in v.items():
                if k in _SELECTION_KEYS and isinstance(val, str) and _UUID.match(val):
                    yield val
                else:
                    yield from walk(val)
        elif isinstance(v, list):
            for x in v:
                yield from walk(x)

    yield from walk(inputs)
