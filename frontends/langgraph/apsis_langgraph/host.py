"""The host of runs: an object whose methods start runs of the graphs it holds and resume interrupted ones. A method
that calls a graph's ``invoke``, ``ainvoke``, ``stream`` or ``astream`` starts a run, and resumes one when it passes
``Command(resume=...)``; read from its source are the fields of the host it assigns, and the fields the thread id of
a resume is taken from."""
from __future__ import annotations

import ast
import inspect
import textwrap

RUN_CALLS = frozenset({"invoke", "ainvoke", "stream", "astream", "astream_events"})


def _def(func):
    try:
        tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    except (OSError, TypeError, SyntaxError):
        return None
    return next((n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))), None)


def _self_field(e, receiver: str) -> str | None:
    """The field of ``receiver.<field>``, else None."""
    if isinstance(e, ast.Attribute) and isinstance(e.value, ast.Name) and e.value.id == receiver:
        return e.attr
    return None


def _guarded(stmt, field: str, receiver: str, parents: dict) -> bool:
    """The assignment sits in an ``if`` that tests the field: an initialization, done once."""
    node = parents.get(stmt)
    while node is not None:
        if isinstance(node, ast.If) and any(_self_field(n, receiver) == field for n in ast.walk(node.test)):
            return True
        node = parents.get(node)
    return False


def _fields_in(expr, assigned: dict, receiver: str, depth: int = 0) -> set:
    """The fields of the receiver an expression reads, through the local names it is computed from."""
    out = set()
    for n in ast.walk(expr):
        field = _self_field(n, receiver)
        if field is not None:
            out.add(field)
        elif isinstance(n, ast.Name) and depth < 4:
            for value in assigned.get(n.id, []):
                out |= _fields_in(value, assigned, receiver, depth + 1)
    return out


def _thread_of(config) -> ast.AST | None:
    """The thread id expression of a ``{"configurable": {"thread_id": ...}}`` literal."""
    if not isinstance(config, ast.Dict):
        return None
    for k, v in zip(config.keys, config.values):
        if isinstance(k, ast.Constant) and k.value == "configurable" and isinstance(v, ast.Dict):
            for k2, v2 in zip(v.keys, v.values):
                if isinstance(k2, ast.Constant) and k2.value == "thread_id":
                    return v2
    return None


def _method(func):
    """``(starts runs, resumes runs, fields assigned, fields a resume's thread id is read from)`` of a method."""
    node = _def(func)
    if node is None or not node.args.args:
        return False, False, set(), set()
    receiver = node.args.args[0].arg
    parents = {child: parent for parent in ast.walk(node) for child in ast.iter_child_nodes(parent)}
    assigned: dict = {}
    for n in ast.walk(node):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    assigned.setdefault(t.id, []).append(n.value)
    sets = set()
    for n in ast.walk(node):
        if isinstance(n, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            for t in n.targets if isinstance(n, ast.Assign) else [n.target]:
                field = _self_field(t, receiver)
                if field is not None and not _guarded(n, field, receiver, parents):
                    sets.add(field)
    starts = resumes = False
    resume_fields = set()
    for n in ast.walk(node):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in RUN_CALLS):
            continue
        config = next((k.value for k in n.keywords if k.arg == "config"), n.args[1] if len(n.args) > 1 else None)
        first = n.args[0] if n.args else None
        is_resume = (isinstance(first, ast.Call) and isinstance(first.func, ast.Name) and first.func.id == "Command"
                     and any(k.arg == "resume" for k in first.keywords))
        resumes |= is_resume
        starts |= not is_resume
        if is_resume and config is not None:
            literal = config
            if isinstance(config, ast.Name):
                literal = next((v for v in assigned.get(config.id, []) if isinstance(v, ast.Dict)), None)
            thread = _thread_of(literal)
            if thread is not None:
                resume_fields |= _fields_in(thread, assigned, receiver)
    return starts, resumes, sets, resume_fields


def host_workflow(host, provenance: dict) -> dict:
    """The host's run-starting and run-resuming methods as the steps of a workflow ``host``."""
    nodes = []
    ident = f"{type(host).__qualname__}@{hex(id(host))}"
    for name, func in inspect.getmembers(type(host), inspect.isfunction):
        if name.startswith("__"):
            continue
        starts, resumes, sets, resume_fields = _method(func)
        if not (starts or resumes):
            continue
        attrs = {}
        if starts:
            attrs["starts_runs"] = "true"
        if sets:
            attrs["sets"] = ",".join(f"{f}:{ident}" for f in sorted(sets))
        if resume_fields:
            attrs["resume_thread"] = ",".join(f"{f}:{ident}" for f in sorted(resume_fields))
        nodes.append({"id": name, "type_name": f"{type(host).__qualname__}.{name}", "kind": "component", "attrs": attrs})
    return {
        "id": "host",
        "execution_model": {"other": "langgraph-host"},
        "framework": "langgraph",
        "nodes": nodes,
        "edges": [],
        "channels": [],
        "provenance": provenance,
    }
