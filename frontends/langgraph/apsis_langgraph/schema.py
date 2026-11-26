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


def _keeps_only_second(reducer) -> bool:
    """A two-argument reducer whose result never uses its first argument (``lambda a, b: b``)."""
    import ast
    import textwrap

    try:
        tree = ast.parse(textwrap.dedent(inspect.getsource(reducer)))
    except (OSError, TypeError, SyntaxError, ValueError):
        return False
    top = next((n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))), None)
    if top is None or len(top.args.args) != 2:
        return False
    first = top.args.args[0].arg
    results = [top.body] if isinstance(top, ast.Lambda) else [n.value for n in ast.walk(top) if isinstance(n, ast.Return)]
    if not results or any(r is None for r in results):
        return False
    return not any(isinstance(n, ast.Name) and n.id == first for n in ast.walk(top))


def _unwrapped(annotation):
    """The annotation inside Required[...], NotRequired[...] and ReadOnly[...]."""
    while getattr(get_origin(annotation), "_name", None) in ("Required", "NotRequired", "ReadOnly"):
        annotation = get_args(annotation)[0]
    return annotation


def _classify(reducer) -> dict:
    """The marker of a reducer function."""
    name = (
        getattr(reducer, "__name__", None)
        or getattr(reducer, "__qualname__", None)
        or type(reducer).__name__
    )
    mod = getattr(reducer, "__module__", "") or ""
    # add_messages (or any reducer from a message module) merges by message id; operator.add concatenates
    if name in ("_add_messages", "add_messages") or "message" in mod:
        return {"messages": None}
    if name == "add" and mod in ("_operator", "operator"):
        return {"append": None}
    if mod in ("_operator", "operator"):
        return {"binary-op": name}
    if _keeps_only_second(reducer):
        return {"overwrite": name}
    return {"custom": name}


def _reducer_of(annotation) -> tuple[dict | None, str]:
    """``(reducer marker, base type)`` of one state-schema field; the marker is None for last-value. As in
    LangGraph, the last item of the ``Annotated`` metadata is the field's channel, or its reducer when callable."""
    annotation = _unwrapped(annotation)
    if get_origin(annotation) is Annotated:
        args = get_args(annotation)
        base_repr = _type_str(_unwrapped(args[0]))
        last = args[-1] if len(args) > 1 else None
        channel = last if isinstance(last, type) else type(last)
        if any(c.__name__ == "BaseChannel" for c in getattr(channel, "__mro__", ())):
            # a channel: the reducer it applies, else its kind
            reducer = getattr(last, "operator", None) or getattr(last, "reducer", None)
            if callable(reducer):
                return _classify(reducer), base_repr
            if channel.__name__ == "Topic":
                return {"append": None}, base_repr
            if channel.__name__.startswith("LastValue"):
                return None, base_repr
            return {"custom": channel.__name__}, base_repr
        if not callable(last):
            return None, base_repr
        return _classify(last), base_repr
    return None, _type_str(annotation)

def _reducer_to_json(red: dict | None):
    if red is None:
        return "last-value"
    if "messages" in red:
        return "messages"
    if "append" in red:
        return "append"
    if "binary-op" in red:
        return {"binary-op": red["binary-op"]}
    if "overwrite" in red:
        return "overwrite"
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
