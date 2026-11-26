"""Read parlant journeys into the IR: a workflow per journey, its states as steps and its transitions as edges.

A journey's transitions stay inside it, which the workflow states as `self_contained`. States get stable ids,
`<journey>/root`, `<journey>/s<n>` in the order the store lists them, so that a transition into another journey's
state names that state."""
from __future__ import annotations

import re

START = "__start__"
END = "__end__"
END_NODE = "end"  # the id parlant gives every journey's end state


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "journey"


def extract(journeys: list, provenance: dict) -> dict:
    try:
        from importlib.metadata import version

        parlant_version = version("parlant")
    except Exception:  # pragma: no cover
        parlant_version = None
    names: dict[str, str] = {}
    slugs: dict[str, str] = {}
    for journey, nodes, _ in journeys:
        slug = _slug(journey.title)
        while slug in slugs.values():
            slug += "-"
        slugs[journey.id] = slug
        k = 0
        for node in nodes:
            if node.id == END_NODE:
                continue
            if node.id == journey.root_id:
                names.setdefault(node.id, f"{slug}/root")
            else:
                k += 1
                names.setdefault(node.id, f"{slug}/s{k}")
    workflows = []
    for journey, nodes, edges in journeys:
        slug = slugs[journey.id]
        steps = [{"id": names[n.id], "name": str(n.action or n.description or ""), "type_name": "parlant.JourneyNode",
                  "kind": "component"} for n in nodes if n.id != END_NODE]
        flow = [{"from": {"node": START, "socket": ""}, "to": {"node": names[journey.root_id], "socket": ""},
                 "kind": "control"}] if journey.root_id in names else []
        for e in edges:
            source = names.get(e.source, e.source)
            target = END if e.target == END_NODE else names.get(e.target, e.target)
            edge = {"from": {"node": source, "socket": ""}, "to": {"node": target, "socket": ""}, "kind": "conditional"
                    if e.condition else "control"}
            if e.condition:
                edge["condition"] = e.condition
            flow.append(edge)
        workflows.append({
            "id": slug,
            "execution_model": {"other": "parlant-journey"},
            "framework": "parlant",
            "framework_version": parlant_version,
            "nodes": steps,
            "edges": flow,
            "channels": [],
            "start_nodes": [names[journey.root_id]] if journey.root_id in names else [],
            "output_nodes": [],
            "attrs": {"self_contained": "true"},
            "provenance": provenance,
        })
    return workflows[0] if len(workflows) == 1 else {"workflows": workflows}
