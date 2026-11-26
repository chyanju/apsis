"""Resolve the entry spec to a built AutoGen orchestration object; ``extract`` dispatches on its shape."""
from __future__ import annotations

from apsis_common.loader import resolve_entry


def _resolve(obj):
    """Call a zero-arg factory once; AutoGen orchestration objects are not callable."""
    if callable(obj) and not isinstance(obj, type):
        try:
            return obj()
        except TypeError:
            return obj
    return obj


def get_workflow(spec: str):
    return resolve_entry(spec, _resolve, "autogen", module_name="apsis_user_workflow")
