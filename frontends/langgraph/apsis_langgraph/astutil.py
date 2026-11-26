"""AST inspection of LangGraph node and routing functions: Command(goto)/Send targets, return labels, channel
reads and writes. A target that cannot be resolved is reported as unresolved, never dropped."""
from __future__ import annotations

import ast
import collections
import enum
import functools
import inspect
import sysconfig
import textwrap
import typing
from typing import get_args, get_origin, get_type_hints

from .schema import _type_str

_SENTINELS = {"END": "__end__", "START": "__start__"}
_SCALARS = (str, bytes, int, float, bool, type(None), enum.Enum)
_STDLIB = sysconfig.get_paths()["stdlib"]

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

def _routine(func):
    """The function behind a callable: through partials, and the bound ``__call__`` of a callable instance."""
    while isinstance(func, functools.partial):
        func = func.func
    if not inspect.isroutine(func) and not inspect.isclass(func) and callable(func):
        return func.__call__
    return func


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

def _local_assignments(tree) -> tuple[dict[str, list], set[str]]:
    """``(name -> every value assigned to it, names bound otherwise: parameters, loop and ``with`` targets, ...)``."""
    assigned: dict[str, list] = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    assigned.setdefault(t.id, []).append(n.value)
        elif isinstance(n, ast.AnnAssign) and n.value is not None and isinstance(n.target, ast.Name):
            assigned.setdefault(n.target.id, []).append(n.value)
    plain = {id(t) for n in ast.walk(tree) if isinstance(n, ast.Assign) for t in n.targets}
    plain |= {id(n.target) for n in ast.walk(tree) if isinstance(n, (ast.AnnAssign, ast.AugAssign))}
    other = {n.arg for n in ast.walk(tree) if isinstance(n, ast.arg)}
    other |= {n.id for n in ast.walk(tree)
              if isinstance(n, ast.Name) and not isinstance(n.ctx, ast.Load) and id(n) not in plain}
    return assigned, other


class _Resolver:
    """Resolve a routing-target expression to the string(s) it denotes."""

    def __init__(self, func, tree, bound: dict | None = None, depth: int = 0):
        func = _routine(func)
        self.func = func
        self.assigned, self.rebound = _local_assignments(tree) if tree is not None else ({}, set())
        code = getattr(func, "__code__", None)
        self.freevars = list(getattr(code, "co_freevars", ()) or ())
        self.closure = getattr(func, "__closure__", None) or ()
        self.globals = getattr(func, "__globals__", {}) or {}
        self.bound = bound or {}  # parameter -> (argument expression, the caller's resolver)
        self.depth = depth
        self.gated: list[str] = []  # labels a called helper returns under a build-time guard
        self.narrow: dict[str, list[str]] = {}  # name -> the strings an enclosing `name in {...}` test admits
        self._busy: set[str] = set()
        try:
            self.hints = get_type_hints(func)
        except Exception:
            self.hints = {}
        # name -> the values added to it: name.append(x), name.insert(i, x), name.extend(xs), name += xs
        self.appended: dict[str, list] = {}
        for n in ast.walk(tree) if tree is not None else ():
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name):
                method, args = n.func.attr, n.args
                if method in ("append", "extend") and args or method == "insert" and len(args) > 1:
                    self.appended.setdefault(n.func.value.id, []).append(args[-1])
            elif isinstance(n, ast.AugAssign) and isinstance(n.op, ast.Add) and isinstance(n.target, ast.Name):
                self.appended.setdefault(n.target.id, []).append(n.value)

    def outer(self, name: str) -> tuple[bool, object]:
        """``(found, value)`` of a closure or module name."""
        if name in self.freevars:
            try:
                return True, self.closure[self.freevars.index(name)].cell_contents
            except (IndexError, ValueError):
                return False, None
        if name in self.globals and not name.startswith("__"):
            return True, self.globals[name]
        return False, None

    def literal(self, node):
        """The literal a name stands for: its single assignment, else the node itself."""
        if isinstance(node, ast.Name) and node.id not in self.rebound and len(self.assigned.get(node.id, ())) == 1:
            return self.assigned[node.id][0]
        return node

    def strings(self, node) -> list[str] | None:
        """The members of a collection of string constants (a literal, or a closure or module value)."""
        node = self.literal(node)
        elts = node.keys if isinstance(node, ast.Dict) else getattr(node, "elts", None)
        if isinstance(node, (ast.Set, ast.List, ast.Tuple, ast.Dict)):
            ok = all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in elts)
            return [e.value for e in elts] if ok else None
        if isinstance(node, ast.Name) and node.id not in self.assigned and node.id not in self.rebound:
            found, value = self.outer(node.id)
            if found and isinstance(value, (set, frozenset, list, tuple, dict)) and all(isinstance(v, str) for v in value):
                return list(value)
        return None

    def table(self, node) -> tuple[list[str], bool] | None:
        """The values of a lookup table, a dict literal or a closure or module dict; None when it is not one."""
        node = self.literal(node)
        if isinstance(node, ast.Dict):
            vals: list[str] = []
            ok = True
            for v in node.values:
                r, k = self.resolve(v)
                vals.extend(r)
                ok = ok and k
            return vals, ok
        if isinstance(node, ast.Name) and node.id not in self.assigned and node.id not in self.rebound:
            found, value = self.outer(node.id)
            if found and isinstance(value, dict):
                return [v for v in value.values() if isinstance(v, str)], all(isinstance(v, str) for v in value.values())
        return None

    def callee_of(self, fn) -> tuple[object, bool]:
        """``(function, takes the receiver first)`` a call names through a closure, a module, the instance of a
        bound method or a parameter annotated with a class; ``(None, False)`` otherwise."""
        attrs: list[str] = []
        root = fn
        while isinstance(root, ast.Attribute):
            attrs.append(root.attr)
            root = root.value
        if not isinstance(root, ast.Name) or root.id in self.assigned:
            return None, False
        receiver = False
        if root.id in self.rebound:
            if attrs and inspect.ismethod(self.func) and root.id == self.func.__code__.co_varnames[0]:
                value = self.func.__self__
            elif len(attrs) == 1 and isinstance(self.hints.get(root.id), type):
                # a method of the parameter's class, called on the instance
                value = self.hints[root.id]
                receiver = not isinstance(inspect.getattr_static(value, attrs[0], None), (staticmethod, classmethod))
            else:
                return None, False
        else:
            found, value = self.outer(root.id)
            if not found:
                return None, False
        try:
            for a in reversed(attrs):
                value = getattr(value, a)
        except Exception:
            return None, False
        if inspect.ismethod(value):
            return value, False
        return (value, receiver) if inspect.isfunction(value) else (None, False)

    def callee(self, fn):
        return self.callee_of(fn)[0]

    def bind(self, call: ast.Call, target, receiver: bool) -> dict[str, ast.AST]:
        """The parameters of `target` the call binds, mapped to the argument expressions."""
        try:
            params = list(inspect.signature(target).parameters.values())
        except (TypeError, ValueError):
            return {}
        positional = [p.name for p in params if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
        out = dict(zip(positional[1:] if receiver else positional, call.args))
        out.update({kw.arg: kw.value for kw in call.keywords if kw.arg})
        return out

    def passthrough(self, call: ast.Call):
        """The argument a call returns: its function returns one of its parameters; None otherwise."""
        target, receiver = self.callee_of(call.func)
        param = _passthrough_param(target) if target is not None else None
        return self.bind(call, target, receiver).get(param) if param else None

    def call(self, node: ast.Call) -> tuple[list[str], bool]:
        """The labels a helper function returns, its parameters bound to the arguments of the call."""
        target, receiver = self.callee_of(node.func)
        if target is None or self.depth >= 3:
            return [], False
        bound = {name: (arg, self) for name, arg in self.bind(node, target, receiver).items()}
        r = _router_return_targets(target, bound, self.depth + 1)
        self.gated.extend(r["gated"])
        return r["labels"], not (r["unresolved"] or r["sends"] or r["fanout"])

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
        if isinstance(node, ast.Call):
            if _ast_call_name(node) == "Send":
                # a goto may list Send packets
                target = _send_target(node)
                return self.resolve(target) if target is not None else ([], False)
            table = self.table(node.func.value) if isinstance(node.func, ast.Attribute) and node.func.attr == "get" else None
            if table is not None:
                # table.get(key, default): a value of the table or the default; without one a miss is None
                default, ok = self.resolve(node.args[1]) if len(node.args) > 1 else ([], False)
                return table[0] + default, table[1] and ok
            return self.call(node)
        if isinstance(node, ast.Subscript):
            return self.table(node.value) or ([], False)
        if isinstance(node, ast.Attribute):
            if node.attr in _SENTINELS:
                return [_SENTINELS[node.attr]], True
            return [], False
        if isinstance(node, ast.Name):
            nm = node.id
            if nm in _SENTINELS:
                return [_SENTINELS[nm]], True
            if nm in self.narrow:
                return list(self.narrow[nm]), True
            if nm in self.bound:
                arg, caller = self.bound[nm]
                return caller.resolve(arg)
            if nm in self.assigned:
                if nm in self._busy:
                    return [], False
                self._busy.add(nm)
                vals, ok = [], nm not in self.rebound
                for v in self.assigned[nm] + self.appended.get(nm, []):
                    r, k = self.resolve(v)
                    vals.extend(r)
                    ok = ok and k
                self._busy.discard(nm)
                return vals, ok
            if nm in self.rebound:
                return [], False
            found, v = self.outer(nm)
            return ([v], True) if found and isinstance(v, str) else ([], False)
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


_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def _reachable_nodes(tree, nested: bool = True):
    """``ast.walk`` that skips the statements after a return, raise, break or continue in the same block and,
    with ``nested=False``, the functions and classes defined inside the function."""
    stack = [tree]
    inside = False
    while stack:
        node = stack.pop()
        if isinstance(node, _SCOPES):
            if inside and not nested:
                continue
            inside = True
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


def _own_code(func) -> bool:
    """The function is code of the workflow's project: not of an installed distribution or the standard library."""
    func = _routine(func)
    code = getattr(getattr(func, "__func__", func), "__code__", None)
    if code is None:
        return False
    path = code.co_filename
    return not ("site-packages" in path or "dist-packages" in path or path.startswith(_STDLIB))


def _passthrough_param(func) -> str | None:
    """The parameter a function returns on every path (``return update``), or None."""
    tree = _node_source_ast(func)
    if tree is None:
        return None
    returns = [n.value for n in _reachable_nodes(tree, nested=False) if isinstance(n, ast.Return)]
    names = {r.id for r in returns if isinstance(r, ast.Name)}
    if not returns or len(names) != 1 or not all(isinstance(r, ast.Name) for r in returns):
        return None
    return names.pop() if names <= _params(tree) else None


def _node_bodies(func, depth: int = 0) -> list:
    """The function of a node and, transitively, the project functions whose result it returns as its own."""
    out = [func]
    tree = _node_source_ast(func)
    if tree is None or depth >= 3 or not _own_code(func):
        return out
    resolver = _Resolver(func, tree)
    for n in _reachable_nodes(tree, nested=False):
        if not isinstance(n, ast.Return) or n.value is None:
            continue
        value = n.value.value if isinstance(n.value, ast.Await) else n.value
        target = resolver.callee(value.func) if isinstance(value, ast.Call) else None
        # a function that hands back its argument is read at the call, see `_Updates`
        if target is not None and _own_code(target) and _passthrough_param(target) is None:
            out.extend(f for f in _node_bodies(target, depth + 1) if f not in out)
    return out


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

def _bound_names(tree) -> set[str]:
    """Parameters and every name the body binds: the names whose value is set while the function runs."""
    out: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.arg):
            out.add(n.arg)
        elif isinstance(n, ast.Name) and not isinstance(n.ctx, ast.Load):
            out.add(n.id)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            out.add(n.name)
        elif isinstance(n, ast.alias):
            out.add((n.asname or n.name).split(".")[0])
    return out


def _router_return_targets(func, bound: dict | None = None, depth: int = 0) -> dict:
    """What a routing function can return; ``gated`` labels are returned only under a build-time guard.
    A helper it calls is read the same way, with ``bound`` mapping its parameters to the call's arguments."""
    res = {"labels": [], "gated": [], "annotation": list(_literal_return_labels(func)), "sends": [],
           "unresolved": False, "fanout": False, "limits": {}}
    tree = _node_source_ast(func)
    if tree is None:
        res["unresolved"] = True
        return res
    resolver = _Resolver(func, tree, bound, depth)
    runtime_names = _bound_names(tree)
    params = _params(tree)

    def state_key(e) -> str | None:
        """The state key an expression is: a read of the state, or a name assigned one."""
        key = _read_key(e, params, of_state=True)
        if key is None and isinstance(e, ast.Name):
            key = next((k for v in resolver.assigned.get(e.id, ()) if (k := _read_key(v, params, of_state=True))), None)
        return key

    def limit_key(st) -> str | None:
        """The state key a statement compares with a bound before it returns: ``if state["n"] > 20: return ...``."""
        if not (isinstance(st, ast.If) and isinstance(st.test, ast.Compare) and len(st.test.ops) == 1):
            return None
        if not isinstance(st.test.ops[0], (ast.Gt, ast.GtE, ast.Lt, ast.LtE)) or not has_return(st.body):
            return None
        left, right = state_key(st.test.left), state_key(st.test.comparators[0])
        return (left or right) if (left is None) != (right is None) else None

    def config_guard(test) -> bool:
        """The build decides the test: it reads build-time data only, or consults a build-time collection or object."""
        if isinstance(test, ast.BoolOp):
            parts = [config_guard(v) for v in test.values]
            return any(parts) if isinstance(test.op, ast.And) else all(parts)
        if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
            return config_guard(test.operand)
        inner = {id(n.value) for n in ast.walk(test) if isinstance(n, ast.Attribute)}
        data = collection = runtime = False
        for n in ast.walk(test):
            if not isinstance(n, (ast.Name, ast.Attribute)) or id(n) in inner:
                continue
            attrs: list[str] = []
            root = n
            while isinstance(root, ast.Attribute):
                attrs.append(root.attr)
                root = root.value
            if not isinstance(root, ast.Name) or root.id in _SENTINELS:
                continue
            if root.id in runtime_names:
                runtime = True
                continue
            found, value = resolver.outer(root.id)
            if not found:
                continue
            try:
                for a in reversed(attrs):
                    value = getattr(value, a)
            except Exception:
                value = object()
            if callable(value) or inspect.ismodule(value):
                continue  # code, not configuration
            data = True
            collection = collection or not isinstance(value, _SCALARS)
        return data and (collection or not runtime)

    def has_return(stmts) -> bool:
        return any(isinstance(n, ast.Return) for st in stmts for n in ast.walk(st))

    def value_of(val, gated: bool) -> None:
        if isinstance(val, ast.Call) and _ast_call_name(val) == "Send":
            vals, ok = resolver.resolve(val)
            res["sends"].extend(vals)
            if not ok:
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
        if isinstance(val, ast.Name) and val.id in resolver.appended:
            built = resolver.assigned.get(val.id, []) + resolver.appended[val.id]
            if sum(len(v.elts) if isinstance(v, (ast.List, ast.Tuple)) else 1 for v in built) >= 2:
                res["fanout"] = True
        if isinstance(val, ast.IfExp):
            g = gated or config_guard(val.test)
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
        limit = next((i for i, st in enumerate(stmts) if limit_key(st)), None)
        for i, st in enumerate(stmts):
            before = limit is not None and i < limit
            if before or i == limit:
                mark = (len(res["labels"]), len(res["gated"]), res["unresolved"])
                lim = res["limits"].setdefault(limit_key(stmts[limit]), {"labels": [], "exit": [], "unresolved": False})
            if before:
                res["unresolved"] = False
            stop, gated = walk_stmt(st, gated)
            if before or i == limit:
                returned = res["labels"][mark[0]:] + res["gated"][mark[1]:]
                if before:
                    # what the block returns ahead of its limit test
                    lim["labels"].extend(returned)
                    lim["unresolved"] = lim["unresolved"] or res["unresolved"]
                    res["unresolved"] = res["unresolved"] or mark[2]
                else:
                    lim["exit"].extend(returned)
            if stop:
                break

    def walk_stmt(st, gated: bool) -> tuple[bool, bool]:
        """``(the block ends here, gated for the rest of the block)``."""
        if isinstance(st, ast.Return):
            if st.value is None:
                res["unresolved"] = True
            else:
                value_of(st.value, gated)
            return True, gated
        if isinstance(st, _TERMINATORS):
            return True, gated
        if isinstance(st, ast.If):
            g = gated or config_guard(st.test)
            test = st.test
            member = (isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], ast.In)
                      and isinstance(test.left, ast.Name))
            admitted = resolver.strings(test.comparators[0]) if member else None
            if admitted is not None:
                # inside `if name in {...}:` the name is one of the members
                outer = resolver.narrow.get(test.left.id)
                resolver.narrow[test.left.id] = admitted
                walk_block(st.body, g)
                if outer is None:
                    del resolver.narrow[test.left.id]
                else:
                    resolver.narrow[test.left.id] = outer
            else:
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
        return False, gated

    funcs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))]
    if funcs:
        top = funcs[0]
        if isinstance(top, ast.Lambda):
            value_of(top.body, False)
        else:
            walk_block(top.body, False)
    else:
        res["unresolved"] = True
    res["gated"].extend(resolver.gated)
    for k in ("labels", "gated", "annotation", "sends"):
        seen: set[str] = set()
        res[k] = [t for t in res[k] if not (t in seen or seen.add(t))]
    return res


# --- channel writes and reads ---

class _Updates:
    """The updates a function returns, as ``(key, value)`` pairs, read through ``await``, ``Command(update=...)``,
    ``dict(...)`` and ``{**spread}``, local names, ``name["key"] = ...`` and calls that hand back their argument."""

    def __init__(self, func, tool: bool = False):
        self.pairs: list[tuple[str, ast.AST]] = []
        self.full = False  # a state-model constructor: the whole state is replaced (LangGraph <= 0.3.29)
        self.tree = _node_source_ast(func)
        if self.tree is None:
            return
        self.resolver = _Resolver(func, self.tree)
        self.keyed: dict[str, list] = {}
        for n in ast.walk(self.tree):
            if isinstance(n, ast.Assign):
                for t in n.targets:
                    if isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name):
                        key = self.key(t.slice)
                        if key is not None:
                            self.keyed.setdefault(t.value.id, []).append((key, n.value))
        # a tool's return value is its result; only a Command it returns updates the state
        for n in _reachable_nodes(self.tree, nested=False):
            if isinstance(n, ast.Return) and n.value is not None:
                self.collect(n.value, 0, set(), update=not tool)

    def key(self, node) -> str | None:
        vals, ok = self.resolver.resolve(node) if isinstance(node, (ast.Constant, ast.Name)) else ([], False)
        return vals[0] if ok and len(vals) == 1 else None

    def collect(self, value, depth: int, seen: set[str], update: bool = True) -> None:
        if depth > 6:
            return
        if isinstance(value, ast.Await):
            self.collect(value.value, depth, seen, update)
        elif isinstance(value, ast.Dict) and update:
            for k, v in zip(value.keys, value.values):
                if k is None:
                    self.collect(v, depth + 1, seen)
                elif (key := self.key(k)) is not None:
                    self.pairs.append((key, v))
        elif isinstance(value, ast.Call):
            name = _ast_call_name(value)
            if name == "Command":
                for kw in value.keywords:
                    if kw.arg == "update":
                        self.collect(kw.value, depth, seen)
            elif not update:
                return
            elif name == "dict":
                self.pairs.extend((kw.arg, kw.value) for kw in value.keywords if kw.arg)
            elif (arg := self.resolver.passthrough(value)) is not None:
                self.collect(arg, depth + 1, seen)
            elif name and name[:1].isupper():
                self.full = True
        elif isinstance(value, ast.Name) and value.id not in seen:
            seen = seen | {value.id}
            for v in self.resolver.assigned.get(value.id, []):
                self.collect(v, depth + 1, seen, update)
            if update:
                self.pairs.extend(self.keyed.get(value.id, []))


def _write_info(func, tool: bool = False) -> tuple[set[str], bool]:
    """``(channels written, full-state update)`` of a node, or of a tool of a tool node."""
    u = _Updates(func, tool)
    return {k for k, _ in u.pairs}, u.full


def _empty(v) -> bool:
    """An empty or falsy literal: the value of a reset."""
    if isinstance(v, ast.Constant):
        return not v.value
    if isinstance(v, (ast.List, ast.Tuple, ast.Set)):
        return not v.elts
    if isinstance(v, ast.Dict):
        return not v.keys
    return isinstance(v, ast.Call) and _ast_call_name(v) in ("list", "dict", "set", "tuple") and not (v.args or v.keywords)


def _write_kinds(func, tool: bool = False) -> tuple[set[str], set[str]]:
    """``(extends, replaces)``: the keys the node writes with the key's current value plus more (``cur + [x]``,
    ``[*cur, x]``, ``{**cur, k: v}``, a copy of it it appends to), and those it writes with new content that leaves
    the current value out. A value written back as it is, or computed from it otherwise, and an empty value (a
    reset) are in neither."""
    u = _Updates(func, tool)
    if u.tree is None:
        return set(), set()
    params = _params(u.tree)
    assigned = u.resolver.assigned

    def derives(v, key: str, seen: set[str]) -> bool:
        for n in ast.walk(v):
            if _read_key(n, params, of_state=True) == key:
                return True
            if isinstance(n, ast.Name) and n.id not in seen:
                seen.add(n.id)
                if any(derives(a, key, seen) for a in assigned.get(n.id, [])):
                    return True
        return False

    def extends(v, key: str, depth: int = 0) -> bool:
        if isinstance(v, ast.BinOp) and isinstance(v.op, ast.Add):
            return derives(v.left, key, set()) or derives(v.right, key, set())
        if isinstance(v, (ast.List, ast.Tuple, ast.Set)):
            return any(isinstance(e, ast.Starred) and derives(e.value, key, set()) for e in v.elts)
        if isinstance(v, ast.Dict):
            return any(k is None and derives(e, key, set()) for k, e in zip(v.keys, v.values))
        if isinstance(v, ast.Name) and depth < 4:
            grown = v.id in u.resolver.appended and any(derives(a, key, set()) for a in assigned.get(v.id, []))
            return grown or any(extends(a, key, depth + 1) for a in assigned.get(v.id, []))
        return False

    ext: set[str] = set()
    rep: set[str] = set()
    for key, v in u.pairs:
        if extends(v, key):
            ext.add(key)
        elif not derives(v, key, set()) and not _empty(v):
            rep.add(key)
    return ext, rep


def _counters(func) -> set[str]:
    """Channels the node writes with a value it steps by addition or subtraction (``n + 1``, ``n += 1``)."""
    u = _Updates(func)
    if u.tree is None:
        return set()
    stepped = {n.target.id for n in ast.walk(u.tree)
               if isinstance(n, ast.AugAssign) and isinstance(n.op, (ast.Add, ast.Sub)) and isinstance(n.target, ast.Name)}

    def steps(v, depth: int = 0) -> bool:
        if isinstance(v, ast.BinOp) and isinstance(v.op, (ast.Add, ast.Sub)):
            return True
        if isinstance(v, ast.Name) and depth < 4:
            return v.id in stepped or any(steps(a, depth + 1) for a in u.resolver.assigned.get(v.id, []))
        return False

    return {k for k, v in u.pairs if steps(v)}


_MUTATORS = {"append", "extend", "insert", "pop", "popitem", "remove", "clear", "update", "setdefault", "add",
             "discard", "appendleft", "extendleft", "popleft"}


def _mutations(func, depth: int = 0, seen: set | None = None) -> dict[int, tuple[str, str]]:
    """Objects that outlive a run, module-level or captured when the workflow was built (closure cells, the
    instance of a bound method), which the function changes: it assigns or deletes an attribute or an item of
    them, or calls a mutating method of a container in them. Functions it defines and project functions it calls
    are read too. ``id(object) -> (access path, type name)``."""
    func = _routine(func)
    seen = set() if seen is None else seen
    out: dict[int, tuple[str, str]] = {}
    if id(func) in seen or depth > 3 or not _own_code(func):
        return out
    seen.add(id(func))
    tree = _node_source_ast(func)
    if tree is None:
        return out
    resolver = _Resolver(func, tree)
    receiver = func.__code__.co_varnames[0] if inspect.ismethod(func) and func.__code__.co_argcount else None

    def held(name: str):
        """The object a name denotes when it outlives the run, else None."""
        if name == receiver:
            return func.__self__
        if name in resolver.assigned or name in resolver.rebound:
            return None
        found, value = resolver.outer(name)
        if not found or inspect.ismodule(value) or inspect.isclass(value) or inspect.isroutine(value):
            return None
        return None if isinstance(value, _SCALARS) else value

    def root_of(e) -> tuple[str | None, str, bool]:
        """``(root name, access path, the path indexes an item)`` of an attribute or subscript chain."""
        parts: list[str] = []
        item = False
        while isinstance(e, (ast.Attribute, ast.Subscript)):
            if isinstance(e, ast.Attribute):
                parts.append("." + e.attr)
            else:
                parts.append("[]")
                item = True
            e = e.value
        if not isinstance(e, ast.Name):
            return None, "", item
        return e.id, e.id + "".join(reversed(parts)), item

    def note(e) -> None:
        name, path, _ = root_of(e)
        obj = held(name) if name else None
        if obj is not None:
            out.setdefault(id(obj), (path, type(obj).__qualname__))

    for n in ast.walk(tree):
        if isinstance(n, (ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Delete)):
            targets = n.targets if isinstance(n, (ast.Assign, ast.Delete)) else [n.target]
            for t in targets:
                for e in (t.elts if isinstance(t, (ast.Tuple, ast.List)) else [t]):
                    if isinstance(e, (ast.Attribute, ast.Subscript)):
                        note(e)
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            if n.func.attr in _MUTATORS:
                name, path, item = root_of(n.func.value)
                obj = held(name) if name else None
                if obj is not None:
                    try:
                        target = eval(compile(ast.Expression(n.func.value), "<path>", "eval"), {name: obj}) if not item else None
                    except Exception:
                        target = None
                    if item or isinstance(target, (list, dict, set, bytearray, collections.deque)):
                        out.setdefault(id(obj), (path, type(obj).__qualname__))
            else:
                # a method of the step's own instance
                target, _ = resolver.callee_of(n.func)
                if inspect.ismethod(target) and receiver and target.__self__ is func.__self__:
                    for k, v in _mutations(target, depth + 1, seen).items():
                        out.setdefault(k, v)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
            target = resolver.callee(n.func)
            if target is not None:
                for k, v in _mutations(target, depth + 1, seen).items():
                    out.setdefault(k, v)
    return out


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


def _params(tree) -> set[str]:
    """The parameter names of the function a source tree holds."""
    top = next((n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))), None)
    return {a.arg for a in ast.walk(top.args) if isinstance(a, ast.arg)} if top is not None else set()


def _read_key(n, params: set[str], of_state: bool = False) -> str | None:
    """The key an expression reads by subscript, attribute, ``.get``, ``getattr`` or an accessor ``f(state, "key")``
    called on a parameter; with ``of_state`` only when the object read is a parameter."""
    def is_param(x) -> bool:
        return isinstance(x, ast.Name) and x.id in params

    arg = None
    if isinstance(n, ast.Subscript):
        if not of_state or is_param(n.value):
            arg = n.slice
    elif isinstance(n, ast.Attribute):
        return n.attr if not of_state or is_param(n.value) else None
    elif isinstance(n, ast.Call):
        name = _ast_call_name(n)
        if name == "get" and n.args and isinstance(n.func, ast.Attribute):
            if not of_state or is_param(n.func.value):
                arg = n.args[0]
        elif len(n.args) >= 2 and (is_param(n.args[0]) or (name == "getattr" and not of_state)):
            arg = n.args[1]
    return arg.value if isinstance(arg, ast.Constant) and isinstance(arg.value, str) else None


def _read_channels(func, channel_names: set[str]) -> set[str]:
    """Channels the body names by subscript, attribute, ``.get`` or ``getattr``, on any object, or through an
    accessor called on a parameter."""
    tree = _node_source_ast(func)
    if tree is None:
        return set()
    params = _params(tree)
    return {k for n in ast.walk(tree) if (k := _read_key(n, params)) in channel_names}

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


def _fixed_calls(func) -> list[str]:
    """Calls a tool makes on objects captured when it was built, with keyword arguments whose values were captured
    then too, as ``method.argument=value``; none when the tool reads the run config, where such values may come
    from."""
    tree = _node_source_ast(func)
    fdef = next((n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))), None) if tree else None
    if fdef is None:
        return []
    params = fdef.args.posonlyargs + fdef.args.args + fdef.args.kwonlyargs
    if any(p.arg == "config" or (p.annotation is not None and "RunnableConfig" in ast.unparse(p.annotation)) for p in params):
        return []
    if any(isinstance(n, ast.Call) and _ast_call_name(n) in ("get_config", "ensure_config") for n in ast.walk(fdef)):
        return []
    code = getattr(func, "__code__", None)
    if code is None:
        return []
    captured = {}
    for name, cell in zip(code.co_freevars, func.__closure__ or ()):
        try:
            captured[name] = cell.cell_contents
        except ValueError:
            pass
    dicts: dict = {}
    for n in ast.walk(fdef):
        if isinstance(n, (ast.Assign, ast.AnnAssign)) and isinstance(n.value, ast.Dict):
            for target in n.targets if isinstance(n, ast.Assign) else [n.target]:
                if isinstance(target, ast.Name):
                    dicts[target.id] = [(k.value, v) for k, v in zip(n.value.keys, n.value.values) if isinstance(k, ast.Constant)]
    out = set()
    for n in ast.walk(fdef):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name)):
            continue
        receiver = captured.get(n.func.value.id)
        if receiver is None or isinstance(receiver, _SCALARS) or inspect.ismodule(receiver) or inspect.isclass(receiver):
            continue
        arguments = [(k.arg, k.value) for k in n.keywords if k.arg]
        for k in n.keywords:
            if k.arg is None and isinstance(k.value, ast.Name):
                arguments += dicts.get(k.value.id, [])
        for arg, value in arguments:
            if isinstance(value, ast.Name) and isinstance(captured.get(value.id), (str, int)) and not isinstance(captured.get(value.id), bool):
                out.add(f"{n.func.attr}.{arg}={captured[value.id]}")
    return sorted(out)


def _required_keys(mdef, param: str) -> set[str]:
    """The keys a function reads from a dict parameter with ``param["key"]``."""
    return {n.slice.value for n in ast.walk(mdef)
            if isinstance(n, ast.Subscript) and isinstance(n.ctx, ast.Load) and isinstance(n.value, ast.Name)
            and n.value.id == param and isinstance(n.slice, ast.Constant) and isinstance(n.slice.value, str)}


def _missing_keys(func) -> list[str]:
    """Keys a dict the function builds lacks where a method it hands the dict to requires them: the dict is a literal
    in a local name with items assigned after it, the method belongs to an object the function captured, and it reads
    the parameter the dict is bound to with ``param["key"]``. ``method.key`` each."""
    tree = _node_source_ast(func)
    fdef = next((n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))), None) if tree else None
    code = getattr(func, "__code__", None)
    if fdef is None or code is None:
        return []
    captured = {}
    for name, cell in zip(code.co_freevars, func.__closure__ or ()):
        try:
            captured[name] = cell.cell_contents
        except ValueError:
            pass
    built: dict = {}
    for n in ast.walk(fdef):
        if isinstance(n, (ast.Assign, ast.AnnAssign)) and isinstance(n.value, ast.Dict):
            for target in n.targets if isinstance(n, ast.Assign) else [n.target]:
                if isinstance(target, ast.Name):
                    keys = [k.value if isinstance(k, ast.Constant) else None for k in n.value.keys]
                    built[target.id] = None if None in keys else set(keys)  # a spread or a computed key: unknown
    for n in ast.walk(fdef):
        if isinstance(n, ast.Assign):
            for target in n.targets:
                if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name) and target.value.id in built:
                    keys = built[target.value.id]
                    if keys is not None:
                        if isinstance(target.slice, ast.Constant):
                            keys.add(target.slice.value)
                        else:
                            built[target.value.id] = None
    out = set()
    for n in ast.walk(fdef):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name)):
            continue
        receiver = captured.get(n.func.value.id)
        if receiver is None or isinstance(receiver, _SCALARS) or inspect.ismodule(receiver) or inspect.isclass(receiver):
            continue
        method = inspect.getattr_static(type(receiver), n.func.attr, None)
        mtree = _node_source_ast(method) if inspect.isfunction(method) else None
        mdef = next((m for m in mtree.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))), None) if mtree else None
        if mdef is None:
            continue
        params = [a.arg for a in mdef.args.posonlyargs + mdef.args.args][1:]
        bound = [(p, a) for p, a in zip(params, n.args)] + [(k.arg, k.value) for k in n.keywords if k.arg]
        for param, arg in bound:
            if isinstance(arg, ast.Name) and built.get(arg.id) is not None:
                for key in sorted(_required_keys(mdef, param) - built[arg.id]):
                    out.add(f"{n.func.attr}.{key}")
    return sorted(out)


def _required_run_inputs(func) -> list[str]:
    """Keys of the run context or the configurable a node cannot run without: it reads the key from either into a
    name, with ``.get("key")`` or ``["key"]``, and raises where the name is None or empty."""
    tree = _node_source_ast(_routine(func)) if func is not None else None
    fdef = next((n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))), None) if tree else None
    if fdef is None:
        return []

    def from_run_inputs(e) -> bool:
        return any((isinstance(n, ast.Name) and n.id in ("context", "configurable"))
                   or (isinstance(n, ast.Attribute) and n.attr == "context")
                   or (isinstance(n, ast.Constant) and n.value == "configurable") for n in ast.walk(e))

    def keys_read(e) -> set[str]:
        out = set()
        for n in ast.walk(e):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get" and n.args
                    and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)
                    and from_run_inputs(n.func.value)):
                out.add(n.args[0].value)
            elif (isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant) and isinstance(n.slice.value, str)
                    and from_run_inputs(n.value)):
                out.add(n.slice.value)
        return out

    read_into: dict = {}
    for n in ast.walk(fdef):
        if isinstance(n, ast.Assign):
            for target in n.targets:
                if isinstance(target, ast.Name):
                    read_into.setdefault(target.id, set()).update(keys_read(n.value) - {"configurable"})
    required = set()
    for n in ast.walk(fdef):
        if not isinstance(n, ast.If) or not any(isinstance(s, ast.Raise) for s in n.body):
            continue
        test = n.test
        name = None
        if isinstance(test, ast.Compare) and isinstance(test.left, ast.Name) and isinstance(test.ops[0], ast.Is):
            name = test.left.id
        elif isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not) and isinstance(test.operand, ast.Name):
            name = test.operand.id
        if name is not None:
            required |= read_into.get(name, set())
    return sorted(required)


def _instance_counters(cls) -> set[str]:
    """Attributes the methods of a class step by one on the instance: ``self.x += 1``, or ``setattr(self, "x", n)``
    (also through ``object.__setattr__``) with ``n`` computed as something plus one."""
    out = set()
    for name, method in inspect.getmembers(cls, inspect.isfunction):
        if not _own_code(method):
            continue
        tree = _node_source_ast(method)
        fdef = next((n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))), None) if tree else None
        if fdef is None or not fdef.args.args:
            continue
        me = fdef.args.args[0].arg
        stepped = {n.targets[0].id for n in ast.walk(fdef)
                   if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
                   and isinstance(n.value, ast.BinOp) and isinstance(n.value.op, ast.Add)
                   and isinstance(n.value.right, ast.Constant) and n.value.right.value == 1}
        for n in ast.walk(fdef):
            if (isinstance(n, ast.AugAssign) and isinstance(n.op, ast.Add) and isinstance(n.target, ast.Attribute)
                    and isinstance(n.target.value, ast.Name) and n.target.value.id == me):
                out.add(n.target.attr)
            elif (isinstance(n, ast.Call) and _ast_call_name(n) in ("setattr", "__setattr__") and len(n.args) == 3
                    and isinstance(n.args[0], ast.Name) and n.args[0].id == me
                    and isinstance(n.args[1], ast.Constant) and isinstance(n.args[2], ast.Name) and n.args[2].id in stepped):
                out.add(n.args[1].value)
    return out


def _rewrap_resets(func) -> list[str]:
    """Counters that objects a tool holds keep on themselves and lose when re-wrapped: the tool's closure holds the
    object, or a dict or list of them; the object's class steps an attribute of the instance by one; and
    ``with_config({})`` gives an instance without the current value. ``Class.attribute`` each."""
    code = getattr(func, "__code__", None)
    if code is None:
        return []
    held = []
    for cell in func.__closure__ or ():
        try:
            value = cell.cell_contents
        except ValueError:
            continue
        values = list(value.values()) if isinstance(value, dict) else list(value) if isinstance(value, (list, tuple)) else [value]
        held += [v for v in values if not isinstance(v, _SCALARS) and hasattr(type(v), "with_config")]
    out = set()
    for obj in held:
        for counter in sorted(_instance_counters(type(obj))):
            before = getattr(obj, counter, None)
            if not isinstance(before, int) or isinstance(before, bool):
                continue
            try:
                object.__setattr__(obj, counter, before + 1)
                after = getattr(obj.with_config({}), counter, None)
            except Exception:
                continue
            finally:
                object.__setattr__(obj, counter, before)
            if after != before + 1:
                out.add(f"{type(obj).__qualname__}.{counter}")
    return sorted(out)


def _single_pass_writes(func) -> list[str]:
    """Keys of the update a node returns from inside a loop after the loop's first item: the loop body ends in a
    ``return`` no condition guards, and the returned update holds, under the key, a value the body builds before it
    (appends to, extends, assigns). The items after the first are never processed."""
    tree = _node_source_ast(_routine(func)) if func is not None else None
    fdef = next((n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))), None) if tree else None
    if fdef is None:
        return []
    out = set()
    for loop in ast.walk(fdef):
        if not isinstance(loop, (ast.For, ast.AsyncFor, ast.While)) or len(loop.body) < 2:
            continue
        last = loop.body[-1]
        if not isinstance(last, ast.Return) or last.value is None:
            continue
        built = set()
        for stmt in loop.body[:-1]:
            for n in ast.walk(stmt):
                if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in _MUTATORS
                        and isinstance(n.func.value, ast.Name)):
                    built.add(n.func.value.id)
                elif isinstance(n, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                    for t in n.targets if isinstance(n, ast.Assign) else [n.target]:
                        if isinstance(t, ast.Name):
                            built.add(t.id)
                        elif isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name):
                            built.add(t.value.id)
        for d in ast.walk(last.value):
            if isinstance(d, ast.Dict):
                for k, v in zip(d.keys, d.values):
                    if (isinstance(k, ast.Constant) and isinstance(k.value, str)
                            and any(isinstance(n, ast.Name) and n.id in built for n in ast.walk(v))):
                        out.add(k.value)
    return sorted(out)
