"""Resolve the entry object to a ``Workflow``, a view of an unbuilt ``WorkflowBuilder``, or a lone ``ChatAgent``."""
from __future__ import annotations

from .version import _AF_VERSION


def _looks_like_workflow(obj) -> bool:
    return hasattr(obj, "executors") and hasattr(obj, "edge_groups")


def _looks_like_builder(obj) -> bool:
    """An unbuilt ``WorkflowBuilder``, read directly so that a workflow ``build()`` rejects is still analyzed."""
    return (
        type(obj).__name__ == "WorkflowBuilder"
        or (hasattr(obj, "_executors") and hasattr(obj, "_edge_groups") and hasattr(obj, "_start_executor"))
    )


class _BuilderView:
    """A ``WorkflowBuilder`` seen through the attributes of a built ``Workflow``."""

    def __init__(self, b):
        self._b = b
        self.executors = dict(getattr(b, "_executors", {}) or {})
        self.edge_groups = list(getattr(b, "_edge_groups", []) or [])
        start = getattr(b, "_start_executor", None)
        self.start_executor_id = _executor_id(start)
        self.max_iterations = getattr(b, "_max_iterations", None)
        self.name = getattr(b, "_name", None)
        self.id = getattr(b, "_name", None)
        self._output_from = list(getattr(b, "_output_from", None) or [])

    def get_output_executors(self):
        return self._output_from


def _executor_id(ex):
    if ex is None:
        return None
    eid = getattr(ex, "id", None)
    if eid is not None:
        return str(eid)
    return str(ex) if isinstance(ex, str) else None


def _resolve_workflow(obj):
    """The ``Workflow`` (or ``_BuilderView``) the entry object is or wraps, or ``None``."""
    if _looks_like_workflow(obj):
        return obj
    if _looks_like_builder(obj):
        return _BuilderView(obj)
    # an agent or adapter that holds a workflow or builder
    for attr in (
        "workflow",
        "_workflow",
        "_inner_workflow",
        "_agent",
        "agent",
        "_adapter",
        "_builder",
        "_workflow_builder",
    ):
        inner = getattr(obj, attr, None)
        if inner is None or inner is obj:
            continue
        if _looks_like_workflow(inner):
            return inner
        if _looks_like_builder(inner):
            return _BuilderView(inner)
        # one more level (adapter -> agent -> workflow)
        for attr2 in ("workflow", "_workflow", "_agent", "agent"):
            inner2 = getattr(inner, attr2, None)
            if _looks_like_workflow(inner2):
                return inner2
            if _looks_like_builder(inner2):
                return _BuilderView(inner2)
    # a hosting adapter's zero-argument workflow factory
    for attr in ("_workflow_factory", "_create_workflow", "workflow_factory"):
        fn = getattr(obj, attr, None)
        if callable(fn):
            try:
                built = fn()
            except Exception:
                continue
            resolved = _resolve_workflow(built) if built is not obj else None
            if resolved is not None:
                return resolved
    for meth in ("as_workflow", "to_workflow"):
        fn = getattr(obj, meth, None)
        if callable(fn):
            try:
                built = fn()
            except Exception:
                continue
            if _looks_like_workflow(built):
                return built
    return None


def _resolve_chat_agent(obj):
    """The lone ``ChatAgent`` the entry is or wraps, or ``None``."""
    cand = obj
    for attr in (None, "agent", "_agent"):
        c = cand if attr is None else getattr(cand, attr, None)
        if c is not None and type(c).__name__ in ("ChatAgent", "Agent") and not _looks_like_workflow(c):
            return c
    return None


def _chat_agent_workflow(agent, provenance: dict) -> dict:
    """The IR workflow of a lone ``ChatAgent``: one agent node, and a tool node and edge per bound tool."""
    name = getattr(agent, "name", None)
    aid = str(name or getattr(agent, "id", None) or "agent")
    nodes = [
        {
            "id": aid,
            "type_name": f"{type(agent).__module__}.{type(agent).__name__}",
            "kind": "agent",
            "inputs": [],
            "outputs": [],
            "name": str(name) if name else None,
            "instance_id": hex(id(agent)),
            "attrs": {},
        }
    ]
    edges = []
    tools = getattr(agent, "tools", None) or getattr(agent, "_tools", None) or []
    for t in tools:
        tname = str(getattr(t, "name", None) or getattr(t, "__name__", None) or type(t).__name__)
        nodes.append(
            {
                "id": tname,
                "type_name": f"{type(t).__module__}.{type(t).__name__}",
                "kind": "tool",
                "inputs": [],
                "outputs": [],
                "name": tname,
                "instance_id": hex(id(t)),
                "attrs": {},
            }
        )
        edges.append({"from": {"node": aid, "socket": ""}, "to": {"node": tname, "socket": ""}, "kind": "tool"})
    return {
        "execution_model": "group-chat-speaker",
        "framework": "agent-framework",
        "framework_version": _AF_VERSION,
        "provenance": provenance,
        "id": aid,
        "nodes": nodes,
        "edges": edges,
        "channels": [],
        "start_nodes": [aid],
        "output_nodes": [aid],
    }
