"""Read PydanticAI agents into the IR: a workflow per run, the agent's model step and its tools, and a workflow for
each run a tool starts, named after the run and the tool that started it.

The calls of one model response run concurrently unless a tool is sequential, so a tool is a fan-out step. A tool of
a started run that changes an object its run shares with the run that started it (the same object in both deps)
changes state that outlives its run."""
from __future__ import annotations

from .changes import changes, render, value_at, UNKNOWN
from .probe import probe, tools

START = "__start__"
END = "__end__"
IMMUTABLE = (int, float, complex, str, bytes, bool, tuple, frozenset, type(None), type)


def _qualname(obj) -> str:
    module = getattr(obj, "__module__", "") or ""
    name = getattr(obj, "__qualname__", type(obj).__qualname__)
    return name if module == "builtins" else f"{module}.{name}"


def _edge(a: str, b: str) -> dict:
    return {"from": {"node": a, "socket": ""}, "to": {"node": b, "socket": ""}, "kind": "control"}


def _shared(change: tuple, run):
    """The object a change reaches that the run shares with the run that started it, or None."""
    target = change[:-1]
    for k in range(len(target) + 1):
        mine, theirs = value_at(run.deps, target[:k]), value_at(run.parent.deps, target[:k])
        if mine is UNKNOWN or theirs is UNKNOWN:
            return None
        if mine is theirs and not isinstance(mine, IMMUTABLE):
            return mine
    return None


def _workflow(run, wf_id: str, provenance: dict, version) -> dict:
    nodes = [{"id": "agent", "name": getattr(run.agent, "name", None), "type_name": _qualname(type(run.agent)),
              "kind": "agent"}]
    edges = [_edge(START, "agent"), _edge("agent", END)]
    for name, tool in tools(run.agent).items():
        attrs = {}
        if not getattr(tool, "sequential", False):
            attrs["fanout"] = "true"
        if run.parent is not None:
            mutated = []
            for change in sorted(changes(tool, run.deps)):
                obj = _shared(change, run)
                if obj is not None:
                    mutated.append(f"{render(change)}:{type(obj).__qualname__}@{hex(id(obj))}")
            if mutated:
                attrs["mutates"] = ",".join(mutated)
        nodes.append({"id": name, "type_name": _qualname(tool.function), "kind": "tool", "attrs": attrs})
        edges += [_edge("agent", name), _edge(name, "agent")]
    return {
        "id": wf_id,
        "execution_model": {"other": "pydantic-ai-agent"},
        "framework": "pydantic-ai",
        "framework_version": version,
        "nodes": nodes,
        "edges": edges,
        "channels": [],
        "start_nodes": ["agent"],
        "output_nodes": ["agent"],
        "provenance": provenance,
    }


def _walk(run, wf_id: str, out: list, provenance: dict, version) -> None:
    out.append(_workflow(run, wf_id, provenance, version))
    seen: dict = {}
    for child in run.children:
        seen[child.tool] = seen.get(child.tool, 0) + 1
        suffix = "" if seen[child.tool] == 1 else f".{seen[child.tool]}"
        _walk(child, f"{wf_id}/{child.tool}{suffix}", out, provenance, version)


def extract(runs: list, provenance: dict) -> dict:
    """The IR of the runs: a program with a workflow per run and per run its tools start."""
    try:
        from importlib.metadata import version

        pydantic_ai_version = version("pydantic-ai-slim")
    except Exception:  # pragma: no cover
        pydantic_ai_version = None
    workflows: list = []
    for i, (agent, deps) in enumerate(runs, 1):
        _walk(probe(agent, deps), "run" if len(runs) == 1 else f"run{i}", workflows, provenance, pydantic_ai_version)
    return {"workflows": workflows}
