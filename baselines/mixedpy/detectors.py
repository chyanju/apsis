"""The five framework-neutral structural detectors of the mixedpy baseline, over a Graph (graph.py)."""
from graph import Graph, reachable_from, sccs


def dangling_edge(g: Graph):
    out = []
    for e in g.edges:
        if e.src not in g.nodes:
            out.append((e.src, f"edge source '{e.src}' is not a declared node"))
        if e.dst not in g.nodes:
            out.append((e.dst, f"edge target '{e.dst}' is not a declared node"))
    return out


def placeholder_dangling(g: Graph):
    """An inline template reference ({{id.data.instance}}) to a node that does not exist."""
    out = []
    for nid, n in g.nodes.items():
        for inp, refs in n.template_inputs.items():
            for r in refs:
                if r not in g.nodes:
                    out.append((nid, f"node '{n.name or nid}' input '{inp}' references missing node '{r}'"))
    return out


def unreachable(g: Graph):
    out = []
    ent = g.entries()
    if not ent:
        return out
    reach = reachable_from(g, ent)
    for nid, n in g.nodes.items():
        if nid not in reach and not n.is_entry:
            out.append((nid, f"node '{n.name or nid}' is unreachable from entry (orphan/island)"))
    return out


def cycle_unbounded(g: Graph):
    """A cycle (SCC) without a bounded-loop control node (Langflow Loop, Flowise seqLoop)."""
    if not g.cycle_decidable:
        return []
    out = []
    for comp in sccs(g):
        if len(comp) == 1:
            (only,) = tuple(comp)
            if only not in g.succ(only):
                continue
        if not any(g.nodes[c].is_loop_control for c in comp):
            out.append((sorted(comp)[0], f"cycle {sorted(comp)} has no bounded-loop control (potential nontermination)"))
    return out


def required_input_unconnected(g: Graph):
    out = []
    for nid, n in g.nodes.items():
        if not n.required_inputs:
            continue
        by_edge = {e.dst_handle for e in g.edges if e.dst == nid}
        by_template = set(n.template_inputs.keys())
        satisfied = by_edge | by_template
        for h in n.required_inputs:
            if h not in satisfied:
                out.append((nid, f"node '{n.name or nid}' required input '{h}' has no producer"))
    return out


ALL = {
    "dangling-edge": dangling_edge,
    "placeholder-dangling": placeholder_dangling,
    "unreachable": unreachable,
    "cycle-unbounded": cycle_unbounded,
    "required-input-unconnected": required_input_unconnected,
}


def run_all(g: Graph):
    fired = {}
    for name, fn in ALL.items():
        res = fn(g)
        if res:
            fired[name] = res
    return fired
