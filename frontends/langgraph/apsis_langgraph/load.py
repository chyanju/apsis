"""Resolve the entry spec to a LangGraph ``StateGraph`` builder, never invoking the graph."""
from __future__ import annotations

import sqlite3

from apsis_common.loader import resolve_entry


def _saver_location(saver) -> str:
    """Where a checkpoint saver keeps its checkpoints: the database file of a SQLite saver, else the saver."""
    conn = getattr(saver, "conn", None)
    if isinstance(conn, sqlite3.Connection):
        files = [row[2] for row in conn.execute("PRAGMA database_list") if row[1] == "main"]
        if files and files[0]:
            return files[0]
    return hex(id(saver))


def _checkpoint(graph, config) -> str | None:
    """The checkpoint a run resumes from, ``<saver type>@<where it saves>#<thread id>``, or None."""
    saver = getattr(graph, "checkpointer", None)
    thread = ((config or {}).get("configurable") or {}).get("thread_id")
    if saver is None or isinstance(saver, bool) or thread is None:
        return None
    return f"{type(saver).__qualname__}@{_saver_location(saver)}#{thread}"


def _run(item) -> dict:
    """One run: a graph, or a ``(graph, config)`` pair with the config the run is invoked with."""
    graph, config = item if isinstance(item, tuple) and len(item) == 2 and isinstance(item[1], dict) else (item, None)
    # the values the run is configured with, beside its thread id
    values = {k: v for k, v in ((config or {}).get("configurable") or {}).items()
              if k != "thread_id" and isinstance(v, (str, int, float, bool))}
    # the keys the run is given in its configurable and in its runtime context
    inputs = sorted(f"{container}.{k}" for container in ("configurable", "context")
                    for k in ((config or {}).get(container) or {}))
    return {"builder": _resolve(graph), "store": getattr(graph, "store", None), "checkpoint": _checkpoint(graph, config),
            "config": values, "inputs": inputs}


def _resolve(obj):
    from langgraph.graph.state import CompiledStateGraph, StateGraph

    # a zero-arg factory: calling it builds the graph without running it
    if callable(obj) and not isinstance(obj, (CompiledStateGraph, StateGraph, list, tuple)):
        obj = obj()

    # an object that starts and resumes runs, with the runs it serves
    if isinstance(obj, dict) and "host" in obj:
        return {"host": obj["host"], "runs": [_run(item) for item in obj.get("runs", [])]}
    # the graphs an application gives separate runs, each with its long-term store and checkpoint
    if isinstance(obj, (list, tuple)) and obj:
        return [_run(item) for item in obj]
    if isinstance(obj, CompiledStateGraph):
        return obj.builder
    if isinstance(obj, StateGraph):
        return obj
    raise TypeError(
        f"expected a CompiledStateGraph or StateGraph, or a list of runs, got {type(obj).__name__}"
    )


def get_graph(spec: str):
    """Return ``(builder, provenance)`` where ``builder`` is a ``StateGraph``."""
    return resolve_entry(spec, _resolve, "langgraph", module_name="apsis_user_graph")
