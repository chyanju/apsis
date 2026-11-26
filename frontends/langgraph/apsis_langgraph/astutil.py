"""AST inspection of LangGraph node and routing functions: Command(goto)/Send targets, return labels, channel
reads and writes. A target that cannot be resolved is reported as unresolved, never dropped."""
from __future__ import annotations

import ast
import functools
import inspect
import textwrap
import typing
from typing import get_args, get_origin, get_type_hints

from .schema import _type_str

_SENTINELS = {"END": "__end__", "START": "__start__"}

def _node_func(spec):
    """The python callable behind a node's runnable, or None."""
    r = getattr(spec, "runnable", None)
    if r is None:
        return None
    if type(r).__name__ == "RunnableWithFallbacks":
        r = r.runnable  # a lookup the wrapper forwards can fail; the fallbacks are not read
    f = getattr(r, "func", None)
    if f is None:
        f = getattr(r, "afunc", None)
        f = getattr(f, "func", f)  # unwrap functools.partial(run_in_executor, None, real)
    return f

def _path_func(path):
    """The python callable behind a conditional edge's ``path`` runnable, or None."""
    for obj in (path, getattr(path, "runnable", None)):
        if obj is None:
            continue
        f = getattr(obj, "func", None)
        if f is None:
            f = getattr(obj, "afunc", None)
            f = getattr(f, "func", f)
        if callable(f):
            return f
    return None

def _node_source_ast(func):
    """The parsed source of a callable (through partials and ``__call__``), or None."""
    while isinstance(func, functools.partial):
        func = func.func
    if not inspect.isroutine(func) and not inspect.isclass(func) and callable(func):
        func = type(func).__call__
    try:
        src = textwrap.dedent(inspect.getsource(func))
        return ast.parse(src)
    except (OSError, TypeError, SyntaxError, ValueError):
        return None

def _ast_call_name(node: ast.Call) -> str | None:
    fn = node.func
    if isinstance(fn, ast.Name):
        return fn.id
    if isinstance(fn, ast.Attribute):
        return fn.attr
    return None


def _send_target(call: ast.Call):
    """The target expression of a ``Send(node, arg)`` call, or None."""
    if call.args:
        return call.args[0]
    return next((k.value for k in call.keywords if k.arg == "node"), None)


# --- name resolution ---

def _str_consts(val) -> list[str]:
    if isinstance(val, ast.Constant) and isinstance(val.value, str):
        return [val.value]
    if isinstance(val, ast.IfExp):
        return _str_consts(val.body) + _str_consts(val.orelse)
    if isinstance(val, (ast.List, ast.Tuple, ast.Set)):
        out: list[str] = []
        for e in val.elts:
            out.extend(_str_consts(e))
        return out
    return []

def _local_str_assignments(tree) -> dict[str, list[str]]:
    """name -> every string constant assigned to it anywhere in the body (flow-insensitive)."""
    out: dict[str, list[str]] = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign):
            vals = _str_consts(n.value)
            if vals:
                for t in n.targets:
                    if isinstance(t, ast.Name):
                        out.setdefault(t.id, []).extend(vals)
        elif isinstance(n, ast.AnnAssign) and n.value is not None and isinstance(n.target, ast.Name):
            vals = _str_consts(n.value)
            if vals:
                out.setdefault(n.target.id, []).extend(vals)
    return out

class _Resolver:
    """Resolve a routing-target expression to the string(s) it denotes."""

    def __init__(self, func, tree):
        self.func = func
        self.local = _local_str_assignments(tree) if tree is not None else {}
        code = getattr(func, "__code__", None)
        self.freevars = list(getattr(code, "co_freevars", ()) or ())
        self.closure = getattr(func, "__closure__", None) or ()
        self.globals = getattr(func, "__globals__", {}) or {}

    def resolve(self, node) -> tuple[list[str], bool]:
        """``(values, resolved)``; ``resolved`` is False for an expression that cannot be evaluated."""
        if isinstance(node, ast.Constant):
            return ([node.value], True) if isinstance(node.value, str) else ([], False)
        if isinstance(node, ast.IfExp):
            a, ra = self.resolve(node.body)
            b, rb = self.resolve(node.orelse)
            return a + b, ra and rb
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            vals: list[str] = []
            ok = True
            for e in node.elts:
                v, r = self.resolve(e)
                vals.extend(v)
                ok = ok and r
            return vals, ok
        if isinstance(node, ast.Call) and _ast_call_name(node) == "Send":
            # a goto may list Send packets
            target = _send_target(node)
            return self.resolve(target) if target is not None else ([], False)
        if isinstance(node, ast.Attribute):
            if node.attr in _SENTINELS:
                return [_SENTINELS[node.attr]], True
            return [], False
        if isinstance(node, ast.Name):
            nm = node.id
            if nm in _SENTINELS:
                return [_SENTINELS[nm]], True
            if nm in self.local:
                return list(self.local[nm]), True
            if nm in self.freevars:
                i = self.freevars.index(nm)
                try:
                    v = self.closure[i].cell_contents
                except (IndexError, ValueError):
                    return [], False
                return ([v], True) if isinstance(v, str) else ([], False)
            v = self.globals.get(nm)
            if isinstance(v, str):
                return [v], True
            return [], False
        return [], False


def _const_targets(call: ast.Call, resolver: _Resolver | None = None) -> list[str]:
    """String targets of a ``Command(goto=...)`` or ``Send(...)`` call."""
    targets: list[str] = []

    def collect(val):
        if resolver is not None:
            vals, _ = resolver.resolve(val)
            targets.extend(vals)
        else:
            targets.extend(_str_consts(val))

    name = _ast_call_name(call)
    if name == "Command":
        for kw in call.keywords:
            if kw.arg == "goto":
                collect(kw.value)
    elif name == "Send":
        target = _send_target(call)
        if target is not None:
            collect(target)
    return targets

_TERMINATORS = (ast.Return, ast.Raise, ast.Continue, ast.Break)


def _reachable_nodes(tree):
    """``ast.walk`` that skips the statements after a return, raise, break or continue in the same block."""
    stack = [tree]
    while stack:
        node = stack.pop()
        yield node
        for _field, value in ast.iter_fields(node):
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, ast.AST):
                        stack.append(item)
                    if isinstance(item, _TERMINATORS):
                        break
            elif isinstance(value, ast.AST):
                stack.append(value)


def _ast_command_send_targets(func) -> tuple[list[str], bool, bool, bool]:
    """``(targets, uses Command(graph=...), has Send, some target unresolved)`` of a node body."""
    tree = _node_source_ast(func)
    if tree is None:
        return [], False, False, False
    resolver = _Resolver(func, tree)
    targets: list[str] = []
    uses_parent = False
    has_send = False
    unresolved = False
    for n in _reachable_nodes(tree):
        if isinstance(n, ast.Call):
            cname = _ast_call_name(n)
            if cname in ("Command", "Send"):
                targets.extend(_const_targets(n, resolver))
                if cname == "Send":
                    has_send = True
                    _, ok = resolver.resolve(n)
                    unresolved = unresolved or not ok
                if cname == "Command":
                    for kw in n.keywords:
                        if kw.arg == "graph":
                            uses_parent = True
                        if kw.arg == "goto":
                            _, ok = resolver.resolve(kw.value)
                            unresolved = unresolved or not ok
    seen: set[str] = set()
    uniq = [t for t in targets if not (t in seen or seen.add(t))]
    return uniq, uses_parent, has_send, unresolved

def _send_only_targets(func) -> list[str]:
    """Nodes reached via ``Send(name, ...)``: they may run as several tasks in one superstep."""
    tree = _node_source_ast(func)
    if tree is None:
        return []
    resolver = _Resolver(func, tree)
    out: list[str] = []
    for n in _reachable_nodes(tree):
        if isinstance(n, ast.Call) and _ast_call_name(n) == "Send":
            out.extend(_const_targets(n, resolver))
    return out


# --- conditional-edge routing functions ---

def _literal_return_labels(func) -> list[str]:
    """Labels declared by a ``Literal[...]`` return annotation (LangGraph reads these when no path map is given)."""
    try:
        hints = get_type_hints(func)
    except Exception:
        return []
    ra = hints.get("return")
    if ra is None:
        return []
    out: list[str] = []
    def walk(t):
        if get_origin(t) is typing.Literal:
            out.extend(a for a in get_args(t) if isinstance(a, str))
        else:
            for a in get_args(t) or ():
                walk(a)
    walk(ra)
    return out

def _router_return_targets(func) -> dict:
    """What a routing function can return; ``gated`` labels are returned only under a closure/global guard."""
    res = {"labels": [], "gated": [], "annotation": list(_literal_return_labels(func)), "sends": [],
           "unresolved": False, "fanout": False}
    tree = _node_source_ast(func)
    if tree is None:
        res["unresolved"] = True
        return res
    resolver = _Resolver(func, tree)
    code = getattr(func, "__code__", None)
    params = set(getattr(code, "co_varnames", ())[: getattr(code, "co_argcount", 0)]) if code else set()
    config_names = set(resolver.freevars) | {n for n in resolver.globals if not n.startswith("__")}
    local_names = set(resolver.local) | params

    def mentions_config(test) -> bool:
        for n in ast.walk(test):
            if isinstance(n, ast.Name) and n.id in config_names and n.id not in local_names and n.id not in _SENTINELS:
                return True
        return False

    def has_return(stmts) -> bool:
        return any(isinstance(n, ast.Return) for st in stmts for n in ast.walk(st))

    def value_of(val, gated: bool) -> None:
        if isinstance(val, ast.Call):
            if _ast_call_name(val) == "Send":
                vals, ok = resolver.resolve(val)
                res["sends"].extend(vals)
                if not ok:
                    res["unresolved"] = True
            else:
                res["unresolved"] = True
            return
        if isinstance(val, (ast.List, ast.Tuple, ast.Set)):
            if len(val.elts) >= 2:
                res["fanout"] = True
            for e in val.elts:
                value_of(e, gated)
            return
        if isinstance(val, (ast.ListComp, ast.GeneratorExp)):
            res["fanout"] = True
            value_of(val.elt, gated)
            return
        if isinstance(val, ast.IfExp):
            g = gated or mentions_config(val.test)
            value_of(val.body, g)
            value_of(val.orelse, g)
            return
        if isinstance(val, ast.BoolOp):
            for e in val.values:
                value_of(e, gated)
            return
        vals, ok = resolver.resolve(val)
        (res["gated"] if gated else res["labels"]).extend(vals)
        if not ok:
            res["unresolved"] = True

    def walk_block(stmts, gated: bool) -> None:
        for st in stmts:
            if isinstance(st, ast.Return):
                if st.value is None:
                    res["unresolved"] = True
                else:
                    value_of(st.value, gated)
                break
            elif isinstance(st, _TERMINATORS):
                break
            elif isinstance(st, ast.If):
                g = gated or mentions_config(st.test)
                walk_block(st.body, g)
                walk_block(st.orelse, g)
                # after a guarded if that returns, the rest of the block runs only when the guard fails: gated
                if g and not gated and (has_return(st.body) or has_return(st.orelse)):
                    gated = True
            elif isinstance(st, (ast.For, ast.AsyncFor, ast.While)):
                walk_block(st.body, gated)
                walk_block(st.orelse, gated)
            elif isinstance(st, (ast.With, ast.AsyncWith)):
                walk_block(st.body, gated)
            elif isinstance(st, ast.Try):
                walk_block(st.body, gated)
                for h in st.handlers:
                    walk_block(h.body, gated)
                walk_block(st.orelse, gated)
                walk_block(st.finalbody, gated)
            elif isinstance(st, ast.Match):
                for c in st.cases:
                    walk_block(c.body, gated)

    funcs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))]
    if funcs:
        top = funcs[0]
        if isinstance(top, ast.Lambda):
            value_of(top.body, False)
        else:
            walk_block(top.body, False)
    else:
        res["unresolved"] = True
    for k in ("labels", "gated", "annotation", "sends"):
        seen: set[str] = set()
        res[k] = [t for t in res[k] if not (t in seen or seen.add(t))]
    return res


# --- channel writes and reads ---

def _update_of(node) -> tuple[set[str], bool]:
    """``(written keys, full-state update)`` of a node's return value (full-state as in LangGraph <= 0.3.29)."""
    if isinstance(node, ast.Dict):
        keys = {k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        return keys, False
    if isinstance(node, ast.Call):
        name = _ast_call_name(node)
        if name == "Command":
            for kw in node.keywords:
                if kw.arg == "update":
                    return _update_of(kw.value)
            return set(), False
        if name == "dict":
            return {kw.arg for kw in node.keywords if kw.arg}, False
        if name and name[:1].isupper():  # a state-model constructor -> full-state overwrite
            return set(), True
    return set(), False

def _local_update_assignments(tree) -> dict[str, list]:
    """name -> every value assigned to it, and the keys of ``name["k"] = ...`` (flow-insensitive)."""
    out: dict[str, list] = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    out.setdefault(t.id, []).append(n.value)
                elif (isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name)
                      and isinstance(t.slice, ast.Constant) and isinstance(t.slice.value, str)):
                    out.setdefault(t.value.id, []).append(t.slice)
        elif isinstance(n, ast.AnnAssign) and n.value is not None and isinstance(n.target, ast.Name):
            out.setdefault(n.target.id, []).append(n.value)
    return out


def _write_info(func) -> tuple[set[str], bool]:
    """``(channels written, full-state update)`` of a node; a returned variable is read through its assignments."""
    tree = _node_source_ast(func)
    if tree is None:
        return set(), False
    local = _local_update_assignments(tree)
    keys: set[str] = set()
    full = False
    for n in _reachable_nodes(tree):
        if isinstance(n, ast.Return) and n.value is not None:
            values = [n.value]
            if isinstance(n.value, ast.Name):
                values = local.get(n.value.id, [])
            for v in values:
                if isinstance(v, ast.Constant) and isinstance(v.value, str):
                    keys.add(v.value)
                    continue
                k, f = _update_of(v)
                keys |= k
                full = full or f
    return keys, full

def _send_payload_keys(func, target: str) -> tuple[set[str], bool]:
    """``(keys, known)`` of the ``arg`` of ``Send(target, arg)`` calls; ``known`` is False for a non-literal ``arg``."""
    tree = _node_source_ast(func)
    if tree is None:
        return set(), True
    resolver = _Resolver(func, tree)
    keys: set[str] = set()
    known = True
    for n in _reachable_nodes(tree):
        if not (isinstance(n, ast.Call) and _ast_call_name(n) == "Send"):
            continue
        tgt = _send_target(n)
        names, _ = resolver.resolve(tgt) if tgt is not None else ([], False)
        if target not in names:
            continue
        arg = n.args[1] if len(n.args) > 1 else next((k.value for k in n.keywords if k.arg == "arg"), None)
        if isinstance(arg, ast.Dict) and all(isinstance(k, ast.Constant) and isinstance(k.value, str) for k in arg.keys):
            keys |= {k.value for k in arg.keys}
        else:
            known = False
    return keys, known


def _read_channels(func, channel_names: set[str]) -> set[str]:
    """Channels the body names by subscript, attribute, ``.get`` or ``getattr``, on any object."""
    tree = _node_source_ast(func)
    if tree is None:
        return set()
    reads: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Subscript):
            sl = n.slice
            if isinstance(sl, ast.Constant) and isinstance(sl.value, str) and sl.value in channel_names:
                reads.add(sl.value)
        elif isinstance(n, ast.Attribute) and n.attr in channel_names:
            reads.add(n.attr)
        elif isinstance(n, ast.Call):
            name = _ast_call_name(n)
            if name == "get" and n.args:
                a = n.args[0]
                if isinstance(a, ast.Constant) and isinstance(a.value, str) and a.value in channel_names:
                    reads.add(a.value)
            elif name == "getattr" and len(n.args) >= 2:
                a = n.args[1]
                if isinstance(a, ast.Constant) and isinstance(a.value, str) and a.value in channel_names:
                    reads.add(a.value)
    return reads

def _injected_args(func) -> bool:
    try:
        hints = get_type_hints(func, include_extras=True)
    except Exception:
        return False
    for ann in hints.values():
        s = str(ann)
        if "Injected" in s:
            return True
    return False

def _return_type_repr(func) -> str:
    try:
        sig = inspect.signature(func)
    except (TypeError, ValueError):
        return "Any"
    ra = sig.return_annotation
    if ra is inspect.Signature.empty:
        return "Any"
    return _type_str(ra)
