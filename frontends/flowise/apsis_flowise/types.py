"""Flowise handle types (``"A | B | C"``) -> the IR type grammar (``Union[A, B, C]``)."""
from __future__ import annotations


def _canon_type(t) -> str:
    if t is None:
        return "Any"
    s = str(t).strip()
    if not s:
        return "Any"
    parts = [p.strip() for p in s.split("|") if p.strip()]
    if len(parts) > 1:
        return "Union[" + ", ".join(parts) + "]"
    return parts[0] if parts else "Any"
