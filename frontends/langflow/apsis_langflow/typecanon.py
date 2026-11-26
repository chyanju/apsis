"""langflow handle types -> the apsis IR type grammar."""
from __future__ import annotations

from typing import Any


def _as_list(x: Any) -> list:
    if x is None:
        return []
    if isinstance(x, list):
        return x
    return [x]


def _canon_type(s: str) -> str:
    """A langflow ``type`` spelling in the IR grammar; ``other``, langflow's untyped handle, is ``Any``."""
    if not s:
        return "Any"
    if s in ("other", "object", "Any", "NestedDict"):
        return "Any"
    for a, b in (("List[", "list["), ("Dict[", "dict["), ("Tuple[", "tuple["), ("Set[", "set[")):
        s = s.replace(a, b)
    return s


def _type_from_handle_types(types: list, py_type: str | None, is_list: bool) -> str:
    """The handle types langflow matches edges on (else the python ``type``), as a ``type_repr``."""
    accepted = [t for t in types if t]
    if accepted:
        inner = accepted[0] if len(accepted) == 1 else "Union[" + ", ".join(accepted) + "]"
    else:
        inner = _canon_type(py_type or "")
    if is_list:
        return f"list[{inner}]"
    return inner
