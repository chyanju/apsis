"""Classify a LangGraph node spec into an IR NodeKind (subflow / human-input / tool / router / component)."""
from __future__ import annotations

import inspect

def _is_subgraph(spec) -> bool:
    r = getattr(spec, "runnable", None)
    return type(r).__name__ == "CompiledStateGraph"

def _tool_names(spec) -> list[str]:
    r = getattr(spec, "runnable", None)
    tbn = getattr(r, "tools_by_name", None)
    if isinstance(tbn, dict):
        return list(tbn.keys())
    return []

def _tool_funcs(spec):
    r = getattr(spec, "runnable", None)
    tbn = getattr(r, "tools_by_name", None)
    funcs = []
    if isinstance(tbn, dict):
        for tool in tbn.values():
            f = getattr(tool, "func", None) or getattr(tool, "coroutine", None)
            if f is not None:
                funcs.append(f)
    return funcs

def _has_interrupt(func) -> bool:
    if func is None:
        return False
    try:
        src = inspect.getsource(func)
    except (OSError, TypeError):
        return False
    return "interrupt(" in src or "interrupt (" in src or "NodeInterrupt" in src

def _node_kind(name, spec, func, has_send, goto_targets, branch_srcs) -> str:
    if _is_subgraph(spec):
        return "subflow"
    if _has_interrupt(func) or any(_has_interrupt(f) for f in _tool_funcs(spec)):
        return "human-input"
    if _tool_names(spec):
        return "tool"
    if name in branch_srcs or len(goto_targets) > 1 or has_send:
        return "router"
    return "component"


