"""Agent Framework front-end: Python ast + local def-use -> Graph; edges built in loops or other functions are missed."""
import ast
from graph import Graph, Node, Edge

NODE_CTOR_HINTS = ("Executor", "Agent", "executor")   # substring match on the constructor name
EDGE_METHODS = {"add_edge", "add_fan_out_edges", "add_fan_in_edges", "set_start_executor"}


def _name(node):
    return node.id if isinstance(node, ast.Name) else None


def _ctor_name(call):
    f = call.func
    if isinstance(f, ast.Attribute):
        return f.attr
    if isinstance(f, ast.Name):
        return f.id
    return ""


def load(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    g = Graph("agent-framework")
    g.cycle_decidable = False   # cycles end on runtime conditions, not a loop node

    varinfo = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            cname = _ctor_name(node.value)
            label = None
            for kw in node.value.keywords:
                if kw.arg in ("id", "name") and isinstance(kw.value, ast.Constant):
                    label = kw.value.value
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    varinfo[tgt.id] = {"ctor": cname, "label": label or tgt.id}

    edges, entries, used = [], set(), set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        m = node.func.attr
        a = node.args
        if m == "add_edge" and len(a) >= 2:
            s, t = _name(a[0]), _name(a[1])
            if s and t:
                edges.append((s, t)); used |= {s, t}
        elif m == "add_fan_out_edges" and len(a) >= 2 and isinstance(a[1], ast.List):
            s = _name(a[0])
            for el in a[1].elts:
                t = _name(el)
                if s and t:
                    edges.append((s, t)); used |= {s, t}
        elif m == "add_fan_in_edges" and len(a) >= 2 and isinstance(a[0], ast.List):
            t = _name(a[1])
            for el in a[0].elts:
                s = _name(el)
                if s and t:
                    edges.append((s, t)); used |= {s, t}
        elif m == "set_start_executor" and a:
            s = _name(a[0])
            if s:
                entries.add(s); used.add(s)

    node_vars = {v for v, i in varinfo.items() if any(h in i["ctor"] for h in NODE_CTOR_HINTS)} | used
    for v in node_vars:
        info = varinfo.get(v, {})
        g.add_node(Node(id=v, name=info.get("label", v), is_entry=(v in entries)))
    for s, t in edges:
        g.add_edge(Edge(src=s, dst=t))
    return g
