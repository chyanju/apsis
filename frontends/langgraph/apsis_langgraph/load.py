"""Resolve the entry spec to a LangGraph ``StateGraph`` builder, never invoking the graph."""
from __future__ import annotations

from apsis_common.loader import resolve_entry


def _resolve(obj):
    from langgraph.graph.state import CompiledStateGraph, StateGraph

    # a zero-arg factory: calling it builds the graph without running it
    if callable(obj) and not isinstance(obj, (CompiledStateGraph, StateGraph)):
        obj = obj()

    if isinstance(obj, CompiledStateGraph):
        return obj.builder
    if isinstance(obj, StateGraph):
        return obj
    raise TypeError(
        f"expected a CompiledStateGraph or StateGraph, got {type(obj).__name__}"
    )


def get_graph(spec: str):
    """Return ``(builder, provenance)`` where ``builder`` is a ``StateGraph``."""
    return resolve_entry(spec, _resolve, "langgraph", module_name="apsis_user_graph")
