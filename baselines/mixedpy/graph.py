"""The workflow graph every mixedpy front-end lifts a workflow into, and the graph helpers of detectors.py."""
from dataclasses import dataclass, field
import sys

sys.setrecursionlimit(10000)


@dataclass
class Node:
    id: str
    kind: str = ""                                      # node type / category
    name: str = ""
    required_inputs: set = field(default_factory=set)   # input names that need a producer
    template_inputs: dict = field(default_factory=dict) # input name -> set of node ids referenced inline ({{id.data.instance}})
    is_entry: bool = False                              # an explicit source (ChatInput / Start)
    is_terminal: bool = False                          # an explicit sink (ChatOutput / End)
    is_loop_control: bool = False                       # a bounded-loop control node (Loop / seqLoop)


@dataclass
class Edge:
    src: str
    dst: str
    src_handle: str = ""
    dst_handle: str = ""                                # the input-handle name this edge satisfies


@dataclass
class Graph:
    framework: str
    nodes: dict = field(default_factory=dict)           # id -> Node
    edges: list = field(default_factory=list)           # [Edge]
    cycle_decidable: bool = True                         # False where cycles end only on runtime conditions

    def add_node(self, n):
        self.nodes[n.id] = n

    def add_edge(self, e):
        self.edges.append(e)

    def succ(self, nid):
        return {e.dst for e in self.edges if e.src == nid}

    def entries(self):
        """Explicit entry nodes, else the nodes without an incoming edge."""
        explicit = {n.id for n in self.nodes.values() if n.is_entry}
        if explicit:
            return explicit
        targets = {e.dst for e in self.edges}
        return {nid for nid in self.nodes if nid not in targets}


def reachable_from(g, seeds):
    seen = set(seeds)
    stack = list(seeds)
    while stack:
        for m in g.succ(stack.pop()):
            if m not in seen:
                seen.add(m)
                stack.append(m)
    return seen


def sccs(g):
    """Tarjan's strongly connected components, as a list of sets."""
    index, low, onstack, stack, out, counter = {}, {}, {}, [], [], [0]
    adj = {nid: [e.dst for e in g.edges if e.src == nid and e.dst in g.nodes] for nid in g.nodes}

    def strong(v):
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        onstack[v] = True
        for w in adj[v]:
            if w not in index:
                strong(w)
                low[v] = min(low[v], low[w])
            elif onstack.get(w):
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = set()
            while True:
                w = stack.pop()
                onstack[w] = False
                comp.add(w)
                if w == v:
                    break
            out.append(comp)

    for v in g.nodes:
        if v not in index:
            strong(v)
    return out
