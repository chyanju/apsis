"""One IR ``Node`` with its sockets from a langflow ``data.nodes[]`` entry."""
from __future__ import annotations

from .nodekind import _BRANCH_OUTPUTS, _node_kind
from .typecanon import _as_list, _type_from_handle_types


def _input_socket(field_name: str, field: dict) -> dict:
    if not isinstance(field, dict):
        field = {}
    input_types = _as_list(field.get("input_types"))
    is_list = bool(field.get("list"))
    # value types are set in the UI (a ``model`` field via its picker), so never connection-only
    _VALUE_TYPES = {"str", "int", "float", "bool", "dict", "code", "table", "slider", "file", "NestedDict", "model"}
    connection_only = bool(input_types) and str(field.get("type")) not in _VALUE_TYPES
    # the engine skips a hidden field (``ParameterHandler.should_skip_field``)
    hidden = field.get("show") is False
    sock = {
        "name": field_name,
        "type_repr": _type_from_handle_types(input_types, field.get("type"), is_list),
        "has_default": "value" in field,
        "variadic": is_list,
        "mandatory": bool(field.get("required")) and not hidden,
        "connection_only": connection_only,
    }
    return sock


def _output_socket(out: dict) -> dict:
    name = out.get("name", "")
    types = _as_list(out.get("types"))
    is_branch = name in _BRANCH_OUTPUTS or bool(out.get("allows_loop")) or name in ("item", "done")
    return {
        "name": name,
        "type_repr": _type_from_handle_types(types, out.get("selected"), False),
        "may_emit": is_branch,
    }


def _build_node(raw: dict) -> dict:
    """The IR ``Node`` of a ``data.nodes[]`` entry, without its ``subflow_ref``."""
    node_data = raw.get("data", {}) or {}
    node_def = node_data.get("node", {}) or {}
    comp_type = node_data.get("type", "")
    node_id = raw.get("id") or node_data.get("id") or comp_type

    template = node_def.get("template", {}) or {}
    inputs = [
        _input_socket(fname, field)
        for fname, field in template.items()
        if isinstance(field, dict)
    ]
    outputs = [_output_socket(o) for o in node_def.get("outputs", []) if isinstance(o, dict)]

    kind = _node_kind(comp_type, node_def, node_data)

    attrs: dict[str, str] = {}
    # tool_mode may be set on the node, its definition or an output
    if node_data.get("tool_mode") or node_def.get("tool_mode") or any(
        o.get("tool_mode") for o in node_def.get("outputs", []) if isinstance(o, dict)
    ):
        attrs["tool_mode"] = "true"
    if node_def.get("beta"):
        attrs["beta"] = "true"
    stream_field = template.get("stream") if isinstance(template.get("stream"), dict) else None
    if stream_field is not None and stream_field.get("value") is not None:
        attrs["stream"] = str(stream_field.get("value")).lower()
    # only a chat output renders a token stream
    if "ChatOutput" in comp_type:
        attrs["accepts_stream"] = "true"
    # A langflow router passes its input to one of two data outputs, which may meet again.
    if kind == "router":
        attrs["branch_outputs"] = "data-gate"

    node = {
        "id": node_id,
        "type_name": comp_type,
        "kind": kind,
        "inputs": inputs,
        "outputs": outputs,
        # Every node of a flow is its own component instance.
        "instance_id": node_id,
    }
    if attrs:
        node["attrs"] = attrs
    return node
