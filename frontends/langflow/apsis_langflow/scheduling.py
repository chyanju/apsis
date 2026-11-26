"""Release-dependent scheduling facts of a langflow flow (``RunnableVerticesManager``): ``activation`` and
``eager_start``. Where the release is unknown, the facts of every release that could apply are written."""
from __future__ import annotations

import re


def _release(version: str | None) -> tuple[int, int, int] | None:
    """``(major, minor, patch)`` of a langflow version string such as ``1.0.19.post2`` or ``1.1.2.dev2``."""
    if not isinstance(version, str):
        return None
    m = re.match(r"\s*v?(\d+)\.(\d+)(?:\.(\d+))?", version)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)


def _cycle_vertices(node_ids: list[str], edges: list[dict]) -> set[str]:
    """The vertices on a cycle (langflow's ``find_cycle_vertices``): those that can reach themselves."""
    succ: dict[str, set[str]] = {n: set() for n in node_ids}
    for e in edges:
        a, b = e["from"]["node"], e["to"]["node"]
        if a in succ and b in succ:
            succ[a].add(b)

    def reach(start: str) -> set[str]:
        seen, stack = set(), list(succ[start])
        while stack:
            cur = stack.pop()
            if cur not in seen:
                seen.add(cur)
                stack.extend(succ[cur])
        return seen

    reachable = {n: reach(n) for n in node_ids}
    return {a for a in node_ids if a in reachable[a]}


def scheduling_facts(nodes: list[dict], edges: list[dict], version: str | None, raw_outputs: dict[str, list]) -> None:
    """Set the facts on one flow's nodes; ``raw_outputs`` maps a node id to its exported output entries."""
    rel = _release(version)
    on_cycle = _cycle_vertices([n["id"] for n in nodes], edges)
    for n in nodes:
        cyc = n["id"] in on_cycle
        is_loop = any(isinstance(o, dict) and o.get("allows_loop") for o in raw_outputs.get(n["id"], []))
        attrs = n.setdefault("attrs", {})
        # waits for every predecessor: up to 1.10.0 off a cycle, up to 1.0.19 on a cycle too
        if rel is None or (rel <= (1, 10, 0) and (not cyc or rel < (1, 1, 0))):
            attrs["activation"] = "all"
        # runnable whenever the scheduler looks at it, without waiting for the steps outside its cycle
        if cyc and (rel is None or (1, 1, 0) <= rel < (1, 2, 0) or ((1, 2, 0) <= rel < (1, 5, 0) and is_loop)):
            attrs["eager_start"] = "true"
        if not attrs:
            del n["attrs"]
