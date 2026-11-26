"""Turn one agent-framework ``Executor`` into an IR ``Node``, with sockets from its ``@handler`` specs."""
from __future__ import annotations

import inspect
import typing

from .typerepr import _type_str, _types_to_repr


def _handler_specs(ex) -> list:
    specs = getattr(ex, "_handler_specs", None)
    return list(specs) if specs else []


def _response_handler_specs(ex) -> list:
    specs = getattr(ex, "_response_handler_specs", None)
    return list(specs) if specs else []


def _spec_output_types(spec: dict) -> list:
    """A handler's declared output types plus those of its ``WorkflowContext[Out]``."""
    otypes = list(spec.get("output_types") or [])
    ctx_ann = spec.get("ctx_annotation")
    if ctx_ann is not None:
        for t in _ctx_output_types(ctx_ann):
            if t not in otypes:
                otypes.append(t)
    return otypes


def _ctx_output_types(ctx_annotation):
    """The ``Out`` types of a ``WorkflowContext[Out, ...]`` annotation."""
    args = typing.get_args(ctx_annotation)
    if not args:
        return []
    out = args[0]
    # Out is a Union: each member is an output type
    members = typing.get_args(out)
    if members:
        return [m for m in members if m is not type(None)]
    return [out]


def _node_kind(ex) -> str:
    name = type(ex).__name__
    if "RequestInfo" in name:
        return "human-input"
    if "WorkflowExecutor" in name:
        return "subflow"
    if "Agent" in name:
        return "agent"
    return "executor"


def _agent_name(ex):
    agent = getattr(ex, "agent", None) or getattr(ex, "_agent", None)
    if agent is not None:
        nm = getattr(agent, "name", None)
        if nm:
            return str(nm)
    return None


def _handoff_targets(ex) -> list[str]:
    ht = getattr(ex, "_handoff_targets", None)
    if ht is None:
        ht = getattr(ex, "handoff_targets", None)
    if not ht:
        return []
    try:
        return sorted(str(t) for t in ht)
    except TypeError:
        return []


def _is_request_response_capable(ex) -> bool:
    return bool(getattr(ex, "is_request_response_capable", False)) or bool(
        getattr(ex, "_response_handler_specs", None)
    )


def _is_request_port(ex, kind: str) -> bool:
    """A plain executor with a ``@response_handler`` (those of agents and hosts serve optional paths)."""
    return kind == "executor" and bool(getattr(ex, "_response_handler_specs", None))


def _declared_yields(ex) -> list:
    """The ``W_Out`` types of the handlers' ``WorkflowContext[Out, W_Out]`` (``Executor.workflow_output_types``)."""
    found = list(getattr(ex, "workflow_output_types", None) or [])
    if not found:
        for spec in _handler_specs(ex) + _response_handler_specs(ex):
            if isinstance(spec, dict):
                found.extend(t for t in spec.get("workflow_output_types") or [] if t not in found)
    return found


def _host_yields(ex) -> list:
    """A sub-workflow host yields its inner outputs only with ``allow_direct_output``; otherwise it sends them on."""
    if not getattr(ex, "allow_direct_output", False):
        return []
    try:
        inner = list(ex.workflow.get_output_executors())
    except Exception:
        return _declared_yields(ex)
    found: list = []
    for e in inner:
        for t in (_host_yields(e) if _node_kind(e) == "subflow" and hasattr(e, "allow_direct_output") else _declared_yields(e)):
            if t not in found:
                found.append(t)
    return found


def _build_node(eid, ex) -> dict:
    kind = _node_kind(ex)
    type_name = f"{type(ex).__module__}.{type(ex).__name__}"

    inputs = []
    outputs = []
    out_seen: set[str] = set()
    out_classes: list = []
    workflow_output_types: list = []
    handlers = [s for s in _handler_specs(ex) if isinstance(s, dict)]
    for spec in handlers:
        hname = spec.get("name") or "handler"
        msg_t = spec.get("message_type")
        inputs.append(
            {
                "name": hname,
                "type_repr": _type_str(msg_t) if msg_t is not None else "Any",
                "mandatory": True,
            }
        )
    # A response handler takes no edge input, but what it sends and yields counts (as in ``Executor.output_types``).
    responders = [s for s in _response_handler_specs(ex) if isinstance(s, dict)]
    for spec in handlers + responders:
        for t in _spec_output_types(spec):
            r = _type_str(t)
            if r and r not in out_seen and r != "None":
                out_seen.add(r)
                out_classes.append(t)
                outputs.append({"name": r, "type_repr": r, "may_emit": True})
        for t in spec.get("workflow_output_types") or []:
            if t not in workflow_output_types:
                workflow_output_types.append(t)

    # no handler specs: fall back to the executor's aggregate declared types
    if not inputs:
        it = getattr(ex, "input_types", None)
        if it:
            inputs.append({"name": "input", "type_repr": _types_to_repr(it), "mandatory": True})
    if not outputs:
        ot = getattr(ex, "output_types", None) or getattr(ex, "_output_types", None)
        if ot:
            for t in ot:
                r = _type_str(t)
                if r and r not in out_seen and r != "None":
                    out_seen.add(r)
                    out_classes.append(t)
                    outputs.append({"name": r, "type_repr": r, "may_emit": True})

    attrs: dict[str, str] = {}
    # The SDK hands a message to a handler of any of its base classes.
    for t in out_classes:
        if inspect.isclass(t):
            bases = [_type_str(b) for b in t.__mro__[1:] if b is not object]
            if bases:
                attrs[f"supertypes:{_type_str(t)}"] = ", ".join(bases)
    if _is_request_response_capable(ex):
        attrs["request_response_capable"] = "true"
    if _is_request_port(ex, kind):
        attrs["request_port"] = "true"
    # Set on every executor: an empty value means it declares no workflow output.
    wot = list(getattr(ex, "workflow_output_types", None) or workflow_output_types)
    if kind == "subflow" and hasattr(ex, "allow_direct_output"):
        wot = _host_yields(ex)
    attrs["workflow_output_types"] = ", ".join(sorted({_type_str(t) for t in wot}))

    node = {
        "id": str(eid),
        "type_name": type_name,
        "kind": kind,
        "inputs": inputs,
        "outputs": outputs,
        "name": _agent_name(ex),
        "declared_targets": _handoff_targets(ex),
        "instance_id": hex(id(ex)),
        "attrs": attrs,
    }
    return node
