"""Canonicalize Python type spellings into the IR type grammar."""
from __future__ import annotations


def _canon(s: str) -> str:
    s = s.replace("typing.", "")
    s = _strip_module_paths(s)
    for a, b in (("List[", "list["), ("Dict[", "dict["), ("Tuple[", "tuple["), ("Set[", "set[")):
        s = s.replace(a, b)
    s = s.replace("NoneType", "None")
    if s in ("object", "Any"):
        return "Any"
    return s


def _strip_module_paths(s: str) -> str:
    """``list[a.b.C] | x.D`` -> ``list[C] | D``."""
    out = []
    token = ""

    def flush() -> None:
        nonlocal token
        if "." in token:
            token = token.rsplit(".", 1)[-1]
        out.append(token)
        token = ""

    for ch in s:
        if ch.isalnum() or ch in "._":
            token += ch
        else:
            flush()
            out.append(ch)
    flush()
    return "".join(out)


def _type_str(t) -> str:
    if t is None:
        return "Any"
    if t is type(None):
        return "None"
    if isinstance(t, type):
        return _canon(getattr(t, "__name__", str(t)))
    return _canon(str(t))


def _types_to_repr(types) -> str:
    """One ``type_repr`` for a set of accepted types (a ``Union[...]`` when more than one)."""
    if types is None:
        return "Any"
    reprs = []
    for t in types:
        r = _type_str(t)
        if r not in reprs:
            reprs.append(r)
    if not reprs:
        return "Any"
    if len(reprs) == 1:
        return reprs[0]
    return "Union[" + ", ".join(reprs) + "]"
