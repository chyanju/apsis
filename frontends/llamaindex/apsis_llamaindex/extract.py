"""Read LlamaIndex workflows into the IR: a step per ``@step`` method, an edge for each event type one step
returns or sends and another accepts, and the facts of concurrent steps, waits and held containers."""
from __future__ import annotations

import ast
import inspect
import textwrap

from apsis_common.toolcalls import pairing_attrs

START = "__start__"
END = "__end__"


def _qualname(cls) -> str:
    return cls.__qualname__ if cls.__module__ == "builtins" else f"{cls.__module__}.{cls.__qualname__}"


def _source(fn):
    try:
        return ast.parse(textwrap.dedent(inspect.getsource(fn)))
    except (OSError, TypeError, SyntaxError, ValueError):
        return None


def _bodies(fn) -> list:
    """The step and the methods of its workflow it calls on ``self``, one level down."""
    out = [fn]
    tree = _source(fn)
    owner = getattr(fn, "__self__", None)
    if tree is None or owner is None:
        return out
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name)
                and n.func.value.id == "self"):
            method = getattr(owner, n.func.attr, None)
            if inspect.ismethod(method) and method not in out:
                out.append(method)
    return out


def _resolve_name(fn, node):
    """The object a name or ``module.name`` in the source of `fn` denotes, or None."""
    fn = getattr(fn, "__func__", fn)
    scope = dict(getattr(fn, "__globals__", {}) or {})
    code = getattr(fn, "__code__", None)
    for name, cell in zip(getattr(code, "co_freevars", ()), getattr(fn, "__closure__", None) or ()):
        try:
            scope[name] = cell.cell_contents
        except ValueError:
            pass
    try:
        return eval(compile(ast.Expression(node), "<name>", "eval"), scope)  # names and attributes only
    except Exception:
        return None


def _calls(fn, method: str):
    tree = _source(fn)
    if tree is None:
        return
    loops = {id(n) for loop in ast.walk(tree) if isinstance(loop, (ast.For, ast.AsyncFor, ast.While))
             for n in ast.walk(loop)}
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == method:
            yield n, id(n) in loops


def _sent(fn) -> list[tuple[type, bool]]:
    """``(event class, sent in a loop)`` for each ``ctx.send_event(Event(...))`` of the function."""
    out = []
    for call, in_loop in _calls(fn, "send_event"):
        arg = call.args[0] if call.args else None
        cls = _resolve_name(fn, arg.func) if isinstance(arg, ast.Call) and isinstance(arg.func, (ast.Name, ast.Attribute)) else None
        if isinstance(cls, type):
            out.append((cls, in_loop))
    return out


def _implicit_waits(fn) -> list[type]:
    """The event classes the function waits for with ``ctx.wait_for_event`` without a ``waiter_id``."""
    out = []
    for call, _ in _calls(fn, "wait_for_event"):
        if any(kw.arg == "waiter_id" for kw in call.keywords) or len(call.args) > 3:
            continue
        cls = _resolve_name(fn, call.args[0]) if call.args and isinstance(call.args[0], (ast.Name, ast.Attribute)) else None
        if isinstance(cls, type):
            out.append(cls)
    return out


def _runs_tools(fn) -> bool:
    return any(True for _ in _calls(fn, "acall")) or any(True for _ in _calls(fn, "call"))


def _tool_functions(workflow) -> list:
    out = []
    for tool in getattr(workflow, "tools", None) or []:
        for name in ("async_fn", "fn"):
            f = getattr(tool, name, None)
            if callable(f) and _source(f) is not None:
                out.append(f)
                break
    return out


def _held_containers(workflow, fn) -> dict[int, str]:
    """``id -> "attr:type"`` for the dict, list and set attributes of the workflow that the step reads."""
    out = {}
    tree = _source(fn)
    if tree is None:
        return out
    for n in ast.walk(tree):
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "self":
            value = getattr(workflow, n.attr, None)
            if isinstance(value, (dict, list, set)):
                out.setdefault(id(value), f"{n.attr}:{type(value).__name__}")
    return out


def _per_item_waiters() -> bool:
    """From llama-index-workflows 2.22.1 an implicit waiter id includes the work item that waits."""
    try:
        from importlib.metadata import version

        parts = tuple(int(p) for p in version("llama-index-workflows").split(".")[:3])
    except Exception:
        return True
    return parts >= (2, 22, 1)


def _workflow(workflow, wf_id: str | None, provenance: dict) -> dict:
    from workflows.events import StartEvent, StopEvent

    steps = workflow._get_steps()
    accepted = {name: list(fn._step_config.accepted_events) for name, fn in steps.items()}
    emitted: dict[str, set] = {}
    looped: set[type] = set()
    for name, fn in steps.items():
        out = {t for t in fn._step_config.return_types if isinstance(t, type) and t is not type(None)}
        for body in _bodies(fn):
            for cls, in_loop in _sent(body):
                out.add(cls)
                if in_loop:
                    looped.add(cls)
        emitted[name] = out
    tools = _tool_functions(workflow)
    per_item = _per_item_waiters()
    nodes, edges = [], []
    for name, fn in steps.items():
        attrs: dict[str, str] = {}
        workers = getattr(fn._step_config, "num_workers", 1) or 1
        # several events of an accepted type in one pass run as concurrent instances
        if workers > 1 and any(issubclass(e, a) for e in looped for a in accepted[name]):
            attrs["fanout"] = "true"
        waits = [w for body in _bodies(fn) for w in _implicit_waits(body)]
        if any(_runs_tools(body) for body in _bodies(fn)):
            attrs["runs_tools"] = "true"
            waits += [w for f in tools for w in _implicit_waits(f)]
        if waits:
            attrs["waits_for"] = ",".join(sorted({_qualname(w) for w in waits}))
            attrs["wait_key"] = "work-item" if per_item else "event"
        held = {}
        for body in _bodies(fn):
            held.update(_held_containers(workflow, body))
        if held:
            attrs["holds"] = ",".join(sorted(f"{v}@{hex(k)}" for k, v in held.items()))
        attrs.update(pairing_attrs(fn, owner=workflow))
        node = {"id": name, "type_name": f"{_qualname(type(workflow))}.{name}", "kind": "component"}
        if attrs:
            node["attrs"] = attrs
        nodes.append(node)
        if any(issubclass(a, StartEvent) for a in accepted[name]):
            edges.append({"from": {"node": START, "socket": ""}, "to": {"node": name, "socket": ""}, "kind": "control"})
        if any(issubclass(e, StopEvent) for e in emitted[name]):
            edges.append({"from": {"node": name, "socket": ""}, "to": {"node": END, "socket": ""}, "kind": "control"})
    for a in steps:
        for b in steps:
            if any(issubclass(e, x) for e in emitted[a] for x in accepted[b]):
                edges.append({"from": {"node": a, "socket": ""}, "to": {"node": b, "socket": ""}, "kind": "control"})
    try:
        from importlib.metadata import version

        runtime = version("llama-index-workflows")
    except Exception:  # pragma: no cover
        runtime = None
    wf = {
        "execution_model": {"other": "llamaindex-workflow"},
        "framework": "llamaindex",
        "framework_version": runtime,
        "nodes": nodes,
        "edges": edges,
        "channels": [],
        "start_nodes": [e["to"]["node"] for e in edges if e["from"]["node"] == START],
        "output_nodes": [e["from"]["node"] for e in edges if e["to"]["node"] == END],
        "provenance": provenance,
    }
    if wf_id is not None:
        wf["id"] = wf_id
    return wf


def extract(workflows: list, provenance: dict) -> dict:
    """The IR of the workflows: one workflow, or a program with a workflow per build."""
    if len(workflows) == 1:
        return _workflow(workflows[0], None, provenance)
    return {"workflows": [_workflow(w, f"workflow{i}", provenance) for i, w in enumerate(workflows, 1)]}
