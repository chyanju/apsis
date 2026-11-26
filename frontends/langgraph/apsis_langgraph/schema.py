"""LangGraph state-schema -> IR channels (one field = one channel; Annotated -> reducer)."""
from __future__ import annotations

import inspect
from typing import Annotated, get_args, get_origin, get_type_hints

from apsis_common.pytypes import canonicalize_python_type as _canon_type


def _builder_schema(builder, role: str):
    found = getattr(builder, f"{role}_schema", None)
    if found is None:  # LangGraph 0.x names them `schema`, `input`, `output`
        found = getattr(builder, "schema" if role == "state" else role, None)
    return found


def _type_str(t) -> str:
    if t is None or t is inspect.Parameter.empty:
        return "Any"
    if isinstance(t, type):
        return _canon_type(t.__name__)
    return _canon_type(str(t))


def _reducer_of(annotation) -> tuple[dict | None, str]:
    """``(reducer marker, base type)`` of one state-schema field; the marker is None for last-value."""
    if get_origin(annotation) is Annotated:
        args = get_args(annotation)
        base = args[0]
        reducer = args[1] if len(args) > 1 else None
        base_repr = _type_str(base)
        if reducer is None:
            return None, base_repr
        name = (
            getattr(reducer, "__name__", None)
            or getattr(reducer, "__qualname__", None)
            or type(reducer).__name__
        )
        mod = getattr(reducer, "__module__", "") or ""
        # add_messages (or any reducer from a message module) and operator.add append
        if name in ("_add_messages", "add_messages") or "message" in mod:
            return {"append": None}, base_repr
        if name == "add" and mod in ("_operator", "operator"):
            return {"append": None}, base_repr
        if mod in ("_operator", "operator"):
            return {"binary-op": name}, base_repr
        return {"custom": name}, base_repr
    return None, _type_str(annotation)

def _reducer_to_json(red: dict | None):
    if red is None:
        return "last-value"
    if "append" in red:
        return "append"
    if "binary-op" in red:
        return {"binary-op": red["binary-op"]}
    if "custom" in red:
        return {"custom": red["custom"]}
    return "last-value"

def _registered_schemas(builder) -> list:
    """Every schema registered with the builder: state, input, output, and each node's and router's input."""
    schemas = getattr(builder, "schemas", None)
    return list(schemas) if isinstance(schemas, dict) else []


def _required_keys(schema) -> set[str]:
    """Required fields of a TypedDict, pydantic model or dataclass schema; every field otherwise."""
    keys = getattr(schema, "__required_keys__", None)
    if isinstance(keys, (set, frozenset)):
        return set(keys)
    fields = getattr(schema, "model_fields", None)
    if isinstance(fields, dict):
        return {k for k, f in fields.items() if getattr(f, "is_required", lambda: True)()}
    dc = getattr(schema, "__dataclass_fields__", None)
    if isinstance(dc, dict):
        import dataclasses

        return {
            k for k, f in dc.items()
            if f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING
        }
    try:
        return set(get_type_hints(schema))
    except Exception:
        return set(getattr(schema, "__annotations__", {}) or {})


def _channels_from_schema(state_schema) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if state_schema is None:
        return out
    try:
        hints = get_type_hints(state_schema, include_extras=True)
    except Exception:
        hints = dict(getattr(state_schema, "__annotations__", {}) or {})
    for field_name, annotation in hints.items():
        red, base_repr = _reducer_of(annotation)
        out[field_name] = {
            "name": field_name,
            "type_repr": base_repr,
            "reducer": _reducer_to_json(red),
        }
    return out
