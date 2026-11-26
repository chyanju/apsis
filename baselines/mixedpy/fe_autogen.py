"""AutoGen front-end: Python ast + local def-use -> Graph of group-chat members, speaker transitions and graph edges."""
import ast
from graph import Graph, Node, Edge

AGENT_HINTS = ("Agent", "Proxy")


def _name(n):
    if isinstance(n, ast.Name):
        return n.id
    if isinstance(n, ast.Constant) and isinstance(n.value, str):
        return n.value
    return None


def _ctor(c):
    f = c.func
    return f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")


def load(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    g = Graph("autogen")
    g.cycle_decidable = False

    varname = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            if any(h in _ctor(node.value) for h in AGENT_HINTS):
                nm = None
                for kw in node.value.keywords:
                    if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                        nm = kw.value.value
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        varname[t.id] = nm or t.id

    def resolve(v):
        return varname.get(v, v)

    members, edges = set(), []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        c = _ctor(node)
        if "GroupChat" in c:
            for kw in node.keywords:
                if kw.arg == "agents" and isinstance(kw.value, ast.List):
                    for el in kw.value.elts:
                        nm = _name(el)
                        if nm:
                            members.add(resolve(nm))
                if kw.arg == "allowed_or_disallowed_speaker_transitions" and isinstance(kw.value, ast.Dict):
                    for k, val in zip(kw.value.keys, kw.value.values):
                        src = _name(k)
                        if src and isinstance(val, ast.List):
                            for el in val.elts:
                                dst = _name(el)
                                if dst:
                                    edges.append((resolve(src), resolve(dst)))
        if isinstance(node.func, ast.Attribute):
            if node.func.attr == "add_edge" and len(node.args) >= 2:
                a, b = _name(node.args[0]), _name(node.args[1])
                if a and b:
                    edges.append((resolve(a), resolve(b)))
            elif node.func.attr == "add_node" and node.args:
                a = _name(node.args[0])
                if a:
                    members.add(resolve(a))

    nodes = set(members)
    for a, b in edges:
        nodes |= {a, b}
    for v in nodes:
        g.add_node(Node(id=v, name=v))
    for a, b in edges:
        g.add_edge(Edge(src=a, dst=b))
    return g
