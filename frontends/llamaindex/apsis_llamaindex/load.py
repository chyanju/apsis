"""Resolve the entry spec to built LlamaIndex workflows, never running them."""
from __future__ import annotations

from apsis_common.loader import resolve_entry


def _resolve(obj) -> list:
    from workflows import Workflow

    # a zero-arg factory: calling it builds the workflow without running it
    if callable(obj) and not isinstance(obj, (Workflow, list, tuple)):
        obj = obj()
    items = list(obj) if isinstance(obj, (list, tuple)) else [obj]
    if not items or not all(isinstance(w, Workflow) for w in items):
        raise TypeError(f"expected a Workflow or a list of workflows, got {type(obj).__name__}")
    return items


def get_workflows(spec: str):
    """Return ``(workflows, provenance)``; several workflows are several builds, each a workflow of the program."""
    return resolve_entry(spec, _resolve, "llamaindex", module_name="apsis_user_workflow")
