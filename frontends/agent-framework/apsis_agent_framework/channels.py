"""Shared-state channels: one ``last-value`` ``Channel`` per state key that the ``get_state`` / ``set_state``
calls in user-authored executor classes name."""
from __future__ import annotations

import inspect
import sys

_STATE_READ = {"get_state", "get_shared_state"}
_STATE_WRITE = {"set_state", "set_shared_state", "update_state", "set_shared_states"}


def _resolve_key_expr(node, module_globals):
    """The channel name a key expression spells (literal, module constant or f-string), or ``None``."""
    import ast

    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        v = module_globals.get(node.id)
        return v if isinstance(v, str) else None
    if isinstance(node, ast.JoinedStr):  # f-string
        parts = []
        for piece in node.values:
            if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
                parts.append(piece.value)
            elif isinstance(piece, ast.FormattedValue):
                inner = piece.value
                if isinstance(inner, ast.Name):
                    v = module_globals.get(inner.id)
                    parts.append(v if isinstance(v, str) else "{" + inner.id + "}")
                elif isinstance(inner, ast.Constant):
                    parts.append(str(inner.value))
                else:
                    parts.append("{?}")
            else:
                return None
        return "".join(parts)
    return None


def _shared_state(workflow) -> tuple[list[dict], dict[str, list[str]]]:
    """``(channels, reads_first)``: the channels, and per executor the keys it first accesses by a read."""
    import ast

    channels: dict[str, dict] = {}
    reads_first: dict[str, list[str]] = {}

    def ch_for(key: str) -> dict:
        return channels.setdefault(
            key,
            {"name": key, "type_repr": "Any", "reducer": "last-value", "writers": [], "readers": []},
        )

    for eid, ex in workflow.executors.items():
        cls = type(ex)
        # skip SDK classes: they access engine-internal state keys
        mod = getattr(cls, "__module__", "") or ""
        if mod.split(".", 1)[0] in ("agent_framework", "azure", "fastapi", "starlette"):
            continue
        try:
            src = inspect.getsource(cls)
        except (OSError, TypeError):
            continue
        try:
            tree = ast.parse(_dedent(src))
        except SyntaxError:
            continue
        gl = getattr(sys.modules.get(cls.__module__, None), "__dict__", {})
        # by where a call ends, so the read in set_state(k, get_state(k) + 1) comes first
        calls = sorted(
            (c for c in ast.walk(tree) if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)),
            key=lambda c: (c.end_lineno, c.end_col_offset),
        )
        first: dict[str, str] = {}
        for call in calls:
            meth = call.func.attr
            if meth not in _STATE_READ and meth not in _STATE_WRITE:
                continue
            if not call.args:
                continue
            key = _resolve_key_expr(call.args[0], gl)
            if key is None:
                continue
            first.setdefault(key, meth)
            ch = ch_for(key)
            if meth in _STATE_WRITE and str(eid) not in ch["writers"]:
                ch["writers"].append(str(eid))
            if meth in _STATE_READ and str(eid) not in ch["readers"]:
                ch["readers"].append(str(eid))
        read_first = sorted(k for k, m in first.items() if m in _STATE_READ)
        if read_first:
            reads_first[str(eid)] = read_first
    return list(channels.values()), reads_first


def _dedent(src: str) -> str:
    import textwrap

    return textwrap.dedent(src)
