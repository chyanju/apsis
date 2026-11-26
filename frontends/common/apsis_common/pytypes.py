"""Canonicalize a Python type spelling into the IR type grammar; the backend compares these strings verbatim."""
from __future__ import annotations

_CONTAINERS = (("List[", "list["), ("Dict[", "dict["), ("Tuple[", "tuple["), ("Set[", "set["))


def canonicalize_python_type(s: str) -> str:
    s = s.replace("typing.", "")
    for a, b in _CONTAINERS:
        s = s.replace(a, b)
    s = s.replace("NoneType", "None")
    return "Any" if s in ("object", "") else s
