"""Import the agent-framework workflow, builder or agent that an entry spec names; it is built, never run."""
from __future__ import annotations

from apsis_common.loader import resolve_entry


# ids of workflows a factory returned on both of two calls; the SDK lets one run at a time own a workflow.
SHARED: set[int] = set()


def _resolve(obj):
    """The entry object, or what it builds when it is a factory (called twice to detect a shared workflow)."""
    if callable(obj) and not hasattr(obj, "executors") and not _is_agent(obj):
        try:
            built = obj()
        except TypeError:
            return obj
        if hasattr(built, "executors"):
            try:
                if obj() is built:
                    SHARED.add(id(built))
            except Exception:
                pass  # no sharing fact without a second call
        return built
    return obj


def get_workflow(spec: str):
    """Return ``(entry_object, provenance)`` for an entry spec ``file.py:attr`` or ``module:attr``."""
    return resolve_entry(spec, _resolve, "agent-framework", module_name="apsis_user_workflow")


def _is_agent(obj) -> bool:
    if isinstance(obj, type):
        return False
    return any(hasattr(obj, a) for a in ("workflow", "_workflow", "chat_client", "agents"))
