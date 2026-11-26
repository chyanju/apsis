"""agent-framework ``EdgeGroup`` -> IR edges (control, conditional or handoff)."""
from __future__ import annotations


def _edge_records(eg, handoff_sources: set[str] | None = None) -> list[dict]:
    """IR edges of one ``EdgeGroup``; ``HandoffBuilder`` emits plain groups, so handoff is read off the source."""
    handoff_sources = handoff_sources or set()
    gtype = type(eg).__name__
    if gtype == "InternalEdgeGroup":
        return []

    if gtype == "SwitchCaseEdgeGroup":
        return _switch_edges(eg)

    is_handoff_group = gtype == "HandoffEdgeGroup" or "Handoff" in gtype
    records = []
    for e in getattr(eg, "edges", []) or []:
        src = getattr(e, "source_id", None)
        tgt = getattr(e, "target_id", None)
        if src is None or tgt is None:
            continue
        if str(src).startswith("internal:"):
            continue
        cond = getattr(e, "condition_name", None)
        rec = {
            "from": {"node": str(src), "socket": ""},
            "to": {"node": str(tgt), "socket": ""},
        }
        if is_handoff_group or str(src) in handoff_sources:
            rec["kind"] = "handoff"
        elif cond:
            rec["kind"] = "conditional"
            rec["branch"] = str(cond)
            rec["condition"] = str(cond)
        else:
            rec["kind"] = "control"
        records.append(rec)
    return records


def _switch_edges(eg) -> list[dict]:
    """One conditional edge per switch case; the default case has branch ``default``."""
    records = []
    src = None
    for e in getattr(eg, "edges", []) or []:
        if getattr(e, "source_id", None):
            src = e.source_id
            break
    cases = getattr(eg, "cases", None) or []
    for case in cases:
        tgt = getattr(case, "target_id", None)
        if tgt is None:
            continue
        cname = getattr(case, "condition_name", None)
        is_default = type(case).__name__.endswith("Default") or cname is None
        branch = "default" if is_default else str(cname)
        records.append(
            {
                "from": {"node": str(src), "socket": ""},
                "to": {"node": str(tgt), "socket": ""},
                "kind": "conditional",
                "branch": branch,
                "condition": None if is_default else str(cname),
            }
        )
    if not records:  # fall back to the raw edges if `cases` is unavailable
        for e in getattr(eg, "edges", []) or []:
            s, t = getattr(e, "source_id", None), getattr(e, "target_id", None)
            if s and t:
                records.append(
                    {
                        "from": {"node": str(s), "socket": ""},
                        "to": {"node": str(t), "socket": ""},
                        "kind": "conditional",
                        "branch": str(getattr(e, "condition_name", "") or "case"),
                    }
                )
    return records
