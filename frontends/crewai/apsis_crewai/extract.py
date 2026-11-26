"""Read built CrewAI crews into the IR: a workflow per crew, with its tasks in order and the agents it lists.

An agent listed twice is two steps, and every task and agent carries its object identity, so objects shared
between crews or listed twice show as one instance."""
from __future__ import annotations

import typing

from . import probe

START = "__start__"
END = "__end__"
MODEL_FIELDS = ("llm", "function_calling_llm")  # the agent fields that take a model


def _qualname(cls) -> str:
    return cls.__qualname__ if cls.__module__ == "builtins" else f"{cls.__module__}.{cls.__qualname__}"


def _accepted(annotation) -> list:
    """The types a model field takes as they are. CrewAI also accepts other values for a model field and builds
    an LLM from their model name, dropping the rest of their configuration, so `Any` is left out."""
    out = []
    for t in typing.get_args(annotation) or (annotation,):
        if typing.get_origin(t) is typing.Annotated:
            t = typing.get_args(t)[0]
        if isinstance(t, type) and t not in (type(None), typing.Any):
            out.append(t)
    return out


def _value_type(value, accepted: list) -> str:
    """The type of a value, spelled as the accepted type it is an instance of, else as its class."""
    return next((_qualname(t) for t in accepted if isinstance(value, t)), _qualname(type(value)))


def _agent(agent, aid: str, nodes: list, edges: list) -> dict:
    node = {"id": aid, "name": getattr(agent, "role", None), "type_name": _qualname(type(agent)), "kind": "agent",
            "instance_id": hex(id(agent)), "inputs": [], "outputs": []}
    fields = getattr(type(agent), "model_fields", {})
    for field in MODEL_FIELDS:
        found, value = probe.given(agent, field)
        if not found:
            value = getattr(agent, field, None)
        if value is None or field not in fields:
            continue
        accepted = _accepted(fields[field].annotation)
        node["inputs"].append({"name": field, "type_repr": " | ".join(_qualname(t) for t in accepted)})
        vid = f"{aid}.{field}"
        nodes.append({"id": vid, "type_name": _qualname(type(value)), "kind": "component",
                      "outputs": [{"name": "value", "type_repr": _value_type(value, accepted)}]})
        edges.append({"from": {"node": vid, "socket": "value"}, "to": {"node": aid, "socket": field}, "kind": "data"})
    rejected = probe.REJECTED.get(id(agent))
    if rejected:
        node["attrs"] = {"rejected_fields": ",".join(sorted(rejected))}
    return node


def _crew(crew, wf_id: str | None, provenance: dict) -> dict:
    nodes: list[dict] = []
    edges: list[dict] = []
    for j, agent in enumerate(crew.agents, 1):
        nodes.append(_agent(agent, f"agent{j}", nodes, edges))
    manager = getattr(crew, "manager_agent", None)
    if manager is not None:
        nodes.append(_agent(manager, "manager", nodes, edges))
    tasks = []
    for k, task in enumerate(crew.tasks, 1):
        tid = f"task{k}"
        label = getattr(task, "name", None) or getattr(task, "description", "")
        nodes.append({"id": tid, "name": str(label)[:80], "type_name": _qualname(type(task)), "kind": "component",
                      "instance_id": hex(id(task))})
        tasks.append(tid)
    # the process runs the tasks in order
    for a, b in zip([START, *tasks], [*tasks, END]):
        edges.append({"from": {"node": a, "socket": ""}, "to": {"node": b, "socket": ""}, "kind": "control"})
    process = getattr(crew.process, "value", str(crew.process))
    try:
        from importlib.metadata import version

        crewai_version = version("crewai")
    except Exception:  # pragma: no cover
        crewai_version = None
    wf = {
        "execution_model": {"other": f"crewai-{process}"},
        "framework": "crewai",
        "framework_version": crewai_version,
        "nodes": nodes,
        "edges": edges,
        "channels": [],
        "start_nodes": tasks[:1],
        "output_nodes": tasks[-1:],
        "provenance": provenance,
    }
    if wf_id is not None:
        wf["id"] = wf_id
    return wf


def extract(crews: list, provenance: dict) -> dict:
    """The IR of the crews: one workflow, or a program with a workflow per crew."""
    if len(crews) == 1:
        return _crew(crews[0], None, provenance)
    return {"workflows": [_crew(c, f"crew{i}", provenance) for i, c in enumerate(crews, 1)]}
