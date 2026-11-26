"""What a tool changes in the deps of its run, read from its source and from the methods and functions it calls.

A path names an object from the deps object: attribute names, ``[]`` for an item, ``name()`` for what a method
returns. A change is the path of the changed object followed by what changes: an attribute, ``[]``, or a method that
changes a builtin container."""
from __future__ import annotations

import ast
import collections
import inspect
import textwrap

# methods that change a builtin container
MUTATORS = frozenset({
    "append", "extend", "insert", "pop", "remove", "clear", "update", "setdefault", "add", "discard", "popitem",
    "sort", "reverse", "appendleft", "extendleft", "popleft", "rotate",
})
CONTAINERS = (list, dict, set, bytearray, collections.deque)
MAX_CALLS = 4  # how deep calls are followed
CTX = "ctx"  # the run context a tool takes; its ``deps`` is the empty path
UNKNOWN = object()


def function_def(func):
    """The ``def`` of a Python function, or None."""
    try:
        tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    except (OSError, TypeError, SyntaxError):
        return None
    return next(
        (n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == func.__name__),
        None,
    )


def value_at(root, path):
    """The object at ``path`` from ``root``; UNKNOWN past an item or a returned value."""
    obj = root
    for seg in path:
        if not seg.isidentifier():
            return UNKNOWN
        try:
            obj = getattr(obj, seg)
        except Exception:
            return UNKNOWN
    return obj


def render(change: tuple) -> str:
    return "".join(seg if seg == "[]" else f".{seg}" for seg in change).lstrip(".")


def changes(tool, deps) -> set:
    """The changes a tool's code makes to what its run's deps reach."""
    node = function_def(tool.function)
    params = [] if node is None else node.args.posonlyargs + node.args.args
    if not getattr(tool, "takes_ctx", False) or not params:
        return set()
    out: set = set()
    _Changes(tool.function, {params[0].arg: CTX}, deps, out, 0, set()).run(node)
    return out


class _Changes(ast.NodeVisitor):
    def __init__(self, func, env: dict, deps, out: set, depth: int, seen: set):
        self.func, self.env, self.deps, self.out, self.depth, self.seen = func, env, deps, out, depth, seen

    def run(self, node) -> None:
        for stmt in node.body:
            self.visit(stmt)

    # nested definitions do not run when the function does
    def visit_FunctionDef(self, node):
        pass

    visit_AsyncFunctionDef = visit_ClassDef = visit_Lambda = visit_FunctionDef

    def path(self, node):
        """The path an expression denotes, CTX, or None."""
        if isinstance(node, ast.Name):
            return self.env.get(node.id)
        if isinstance(node, ast.Await):
            return self.path(node.value)
        if isinstance(node, ast.Attribute):
            base = self.path(node.value)
            if base == CTX:
                return () if node.attr == "deps" else None
            return None if base is None else base + (node.attr,)
        if isinstance(node, ast.Subscript):
            base = self.path(node.value)
            return base + ("[]",) if isinstance(base, tuple) else None
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            base = self.path(node.func.value)
            return base + (f"{node.func.attr}()",) if isinstance(base, tuple) else None
        return None

    def change(self, target, what: str) -> None:
        if isinstance(target, tuple):
            self.out.add(target + (what,))

    def bind(self, target, alias) -> None:
        if isinstance(target, ast.Name):
            if alias is None:
                self.env.pop(target.id, None)
            else:
                self.env[target.id] = alias
        elif isinstance(target, ast.Attribute):
            self.visit(target.value)
            self.change(self.path(target.value), target.attr)
        elif isinstance(target, ast.Subscript):
            self.visit(target.value)
            self.visit(target.slice)
            self.change(self.path(target.value), "[]")
        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                self.bind(elt, None)
        elif isinstance(target, ast.Starred):
            self.bind(target.value, None)

    def visit_Assign(self, node):
        self.visit(node.value)
        alias = self.path(node.value)
        for target in node.targets:
            self.bind(target, alias)

    def visit_AnnAssign(self, node):
        if node.value is not None:
            self.visit(node.value)
            self.bind(node.target, self.path(node.value))

    def visit_AugAssign(self, node):
        self.visit(node.value)
        if isinstance(node.target, ast.Name):
            # `x += ...` changes a container in place
            p = self.env.get(node.target.id)
            if isinstance(p, tuple) and isinstance(value_at(self.deps, p), CONTAINERS):
                self.out.add(p + ("+=",))
        else:
            self.bind(node.target, None)

    def visit_Delete(self, node):
        for target in node.targets:
            if isinstance(target, ast.Attribute):
                self.change(self.path(target.value), target.attr)
            elif isinstance(target, ast.Subscript):
                self.change(self.path(target.value), "[]")

    def visit_For(self, node):
        self.visit(node.iter)
        p = self.path(node.iter)
        self.bind(node.target, p + ("[]",) if isinstance(p, tuple) else None)
        for stmt in node.body + node.orelse:
            self.visit(stmt)

    visit_AsyncFor = visit_For

    def visit_With(self, node):
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars is not None:
                self.bind(item.optional_vars, None)
        for stmt in node.body:
            self.visit(stmt)

    visit_AsyncWith = visit_With

    def visit_Call(self, node):
        self.generic_visit(node)
        args = [self.path(a) for a in node.args]
        kwargs = {k.arg: self.path(k.value) for k in node.keywords if k.arg}
        f = node.func
        if isinstance(f, ast.Attribute):
            receiver = self.path(f.value)
            if not isinstance(receiver, tuple):
                return
            obj = value_at(self.deps, receiver)
            method = None if obj is UNKNOWN else inspect.getattr_static(type(obj), f.attr, None)
            if inspect.isfunction(method):
                self.follow(method, [receiver, *args], kwargs)
            elif f.attr in MUTATORS and (obj is UNKNOWN or isinstance(obj, CONTAINERS)):
                self.change(receiver, f"{f.attr}()")
        elif isinstance(f, ast.Name):
            callee = self.lookup(f.id)
            if inspect.isfunction(callee):
                self.follow(callee, args, kwargs)

    def lookup(self, name: str):
        code = self.func.__code__
        if name in code.co_freevars and self.func.__closure__:
            try:
                return self.func.__closure__[code.co_freevars.index(name)].cell_contents
            except ValueError:
                return None
        return self.func.__globals__.get(name)

    def follow(self, callee, args: list, kwargs: dict) -> None:
        """Read the changes of a called function, its parameters bound to the paths of its arguments."""
        if self.depth >= MAX_CALLS:
            return
        node = function_def(callee)
        if node is None:
            return
        positional = [a.arg for a in node.args.posonlyargs + node.args.args]
        names = set(positional) | {a.arg for a in node.args.kwonlyargs}
        env = {name: p for name, p in zip(positional, args) if p is not None}
        env.update({name: p for name, p in kwargs.items() if p is not None and name in names})
        key = (callee, tuple(sorted(env.items(), key=lambda kv: kv[0])))
        if not env or key in self.seen:
            return
        self.seen.add(key)
        _Changes(callee, env, self.deps, self.out, self.depth + 1, self.seen).run(node)
