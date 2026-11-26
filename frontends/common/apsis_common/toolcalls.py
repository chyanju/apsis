"""Tool calls and the tool messages that answer them, read from the code of a step and the functions it calls.

A model turn carries tool calls, each with an id, and a history that goes back to a model holds, for each call, a
tool message that names that id. Read here are two ways a step breaks that pairing:

- it builds tool messages for a part of the calls or results it has, picked by a condition, and for no other part,
  so the calls left out get no tool message;
- a tool message takes the id of its call from a fresh value (uuid, secrets, random), alone or as the fallback
  where the id is missing, so it names no call.

A tool message is a constructor call of a tool-result type, a message with role ``tool``, or a dict with
``"role": "tool"``; the field that names the call is ``tool_call_id`` or ``call_id``."""
from __future__ import annotations

import ast
import inspect
import textwrap

TOOL_RESULT_TYPES = frozenset({"ToolMessage", "ToolResultMessage", "FunctionExecutionResult", "FunctionResultContent"})
ROLE_MESSAGE_TYPES = frozenset({"ChatMessage", "Message", "BaseMessage", "ChatMessageContent"})
CALL_FIELDS = ("tool_call_id", "call_id")
FRESH_MODULES = frozenset({"uuid", "secrets", "random"})
COMPLEMENTS = {ast.In: ast.NotIn, ast.NotIn: ast.In, ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.Is: ast.IsNot,
               ast.IsNot: ast.Is, ast.Lt: ast.GtE, ast.GtE: ast.Lt, ast.Gt: ast.LtE, ast.LtE: ast.Gt}
MAX_CALLS = 3  # how deep calls are followed
LOOPS = (ast.For, ast.AsyncFor)
COMPREHENSIONS = (ast.ListComp, ast.GeneratorExp, ast.SetComp)


def _def(func):
    try:
        tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    except (OSError, TypeError, SyntaxError):
        return None
    name = getattr(func, "__name__", None)
    return next((n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name), None)


def _is_tool_role(e) -> bool:
    return (isinstance(e, ast.Constant) and e.value == "tool") or (isinstance(e, ast.Attribute) and e.attr == "TOOL")


def tool_message_reference(node):
    """``(True, expression of the call id or None)`` when the node builds a tool message, else ``(False, None)``."""
    if isinstance(node, ast.Dict):
        fields = {k.value: v for k, v in zip(node.keys, node.values) if isinstance(k, ast.Constant)}
        if _is_tool_role(fields.get("role")):
            return True, next((fields[f] for f in CALL_FIELDS if f in fields), None)
        return False, None
    if not isinstance(node, ast.Call):
        return False, None
    f = node.func
    name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
    keywords = {k.arg: k.value for k in node.keywords if k.arg}
    if name in TOOL_RESULT_TYPES or (name in ROLE_MESSAGE_TYPES and _is_tool_role(keywords.get("role"))):
        for field in CALL_FIELDS:
            if field in keywords:
                return True, keywords[field]
        extra = keywords.get("additional_kwargs")
        if isinstance(extra, ast.Dict):
            fields = {k.value: v for k, v in zip(extra.keys, extra.values) if isinstance(k, ast.Constant)}
            return True, next((fields[f] for f in CALL_FIELDS if f in fields), None)
        return True, None
    return False, None


def _renamed(cond, var: str):
    """A copy of a condition with its loop variable named ``_``, so conditions of different loops compare."""
    class Rename(ast.NodeTransformer):
        def visit_Name(self, n):
            return ast.copy_location(ast.Name(id="_", ctx=n.ctx), n) if n.id == var else n

    return Rename().visit(ast.parse(ast.unparse(cond), mode="eval")).body


def _excludes(a, b) -> bool:
    """Two conditions that cover every case between them: ``c`` and ``not c``, or a comparison and its complement."""
    if isinstance(a, ast.UnaryOp) and isinstance(a.op, ast.Not):
        return ast.dump(a.operand) == ast.dump(b)
    if isinstance(b, ast.UnaryOp) and isinstance(b.op, ast.Not):
        return ast.dump(b.operand) == ast.dump(a)
    if isinstance(a, ast.Compare) and isinstance(b, ast.Compare) and len(a.ops) == len(b.ops) == 1:
        return (ast.dump(a.left) == ast.dump(b.left) and ast.dump(a.comparators[0]) == ast.dump(b.comparators[0])
                and COMPLEMENTS.get(type(a.ops[0])) is type(b.ops[0]))
    return False


class _Function:
    """One function's source: the values its local names are assigned, and the parent of each node."""

    def __init__(self, func, node):
        self.func, self.node = func, node
        self.assigned: dict = {}
        for n in ast.walk(node):
            if isinstance(n, ast.Assign):
                for t in n.targets:
                    if isinstance(t, ast.Name):
                        self.assigned.setdefault(t.id, []).append(n.value)
            elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.value is not None:
                self.assigned.setdefault(n.target.id, []).append(n.value)
        self.parents = {c: p for p in ast.walk(node) for c in ast.iter_child_nodes(p)}
        self.loops: set = set()  # the loops tool messages are built in

    def raised(self, site):
        """The part of a loop's items a ``raise`` at ``site`` stops on, for a loop that builds tool messages: an
        error ends the run, so those items are left with no silent gap. ``(source text, parts)`` or None."""
        guards = []
        child, parent = site, self.parents.get(site)
        while parent is not None:
            if isinstance(parent, ast.If):
                if child in parent.body:
                    guards.append(parent.test)
                elif child in parent.orelse:
                    guards.append(ast.UnaryOp(op=ast.Not(), operand=parent.test))
            if parent in self.loops and child in parent.body:
                return self._narrowed(parent.iter, parent.target.id, guards)
            child, parent = parent, self.parents.get(parent)
        return None

    def resolve(self, e):
        """The object a name, or an attribute of a module, denotes in the function's closure or module."""
        if isinstance(e, ast.Name):
            code = getattr(self.func, "__code__", None)
            if code is not None and e.id in code.co_freevars and self.func.__closure__:
                try:
                    return self.func.__closure__[code.co_freevars.index(e.id)].cell_contents
                except ValueError:
                    return None
            return getattr(self.func, "__globals__", {}).get(e.id)
        if isinstance(e, ast.Attribute):
            base = self.resolve(e.value)
            return getattr(base, e.attr, None) if inspect.ismodule(base) else None
        return None

    def fresh(self, e, depth: int = 0) -> bool:
        """The expression may evaluate to a value generated anew: a call into uuid, secrets or random."""
        for n in ast.walk(e):
            if isinstance(n, ast.Call) and getattr(self.resolve(n.func), "__module__", None) in FRESH_MODULES:
                return True
            if isinstance(n, ast.Name) and depth < 3 and any(self.fresh(v, depth + 1) for v in self.assigned.get(n.id, [])):
                return True
        return False

    def parts(self, source, depth: int = 0):
        """The items a loop iterates, as ``[(collection, [conditions])]``: a comprehension over a collection is the
        part its conditions pick, a list of starred parts is their union, a name is what it is assigned once; None
        when the source is not known to be a part of anything."""
        if isinstance(source, COMPREHENSIONS) and len(source.generators) == 1:
            gen = source.generators[0]
            if not isinstance(gen.target, ast.Name):
                return None
            return [(ast.unparse(gen.iter), [_renamed(c, gen.target.id) for c in gen.ifs])]
        if isinstance(source, (ast.List, ast.Tuple)) and source.elts:
            out = []
            for elt in source.elts:
                sub = self.parts(elt.value if isinstance(elt, ast.Starred) else elt, depth)
                if sub is None:
                    return None
                out += sub
            return out
        if isinstance(source, ast.Name) and depth < 4:
            values = self.assigned.get(source.id, [])
            if len(values) == 1:
                return self.parts(values[0], depth + 1)
        return None

    def answered(self, site, reference):
        """The part of a collection a tool message built at ``site`` is built for: the loop or comprehension whose
        variable the call id is read from, narrowed by the conditions between it and the site. ``(source text,
        parts)`` or None."""
        used = {n.id for n in ast.walk(reference) if isinstance(n, ast.Name)} if reference is not None else set()
        guards = []
        child, parent = site, self.parents.get(site)
        while parent is not None:
            if isinstance(parent, ast.If):
                if child in parent.body:
                    guards.append(parent.test)
                elif child in parent.orelse:
                    guards.append(ast.UnaryOp(op=ast.Not(), operand=parent.test))
            if isinstance(parent, LOOPS) and child in parent.body and isinstance(parent.target, ast.Name) and parent.target.id in used:
                self.loops.add(parent)
                return self._narrowed(parent.iter, parent.target.id, guards)
            if isinstance(parent, COMPREHENSIONS):
                for gen in parent.generators:
                    if isinstance(gen.target, ast.Name) and gen.target.id in used:
                        return self._narrowed(gen.iter, gen.target.id, guards + list(gen.ifs))
            child, parent = parent, self.parents.get(parent)
        return None

    def _narrowed(self, iterated, var: str, conditions):
        own = [_renamed(c, var) for c in conditions if var in {n.id for n in ast.walk(c) if isinstance(n, ast.Name)}]
        parts = self.parts(iterated)
        if parts is None:
            parts = [(ast.unparse(iterated), [])]
        return ast.unparse(iterated), [(source, conds + own) for source, conds in parts]


def _covered(parts) -> bool:
    """The parts together hold every item of their collection: merging two parts that differ only in a condition and
    its complement, as long as one can, leaves a part with no condition."""
    terms = [list(conds) for _, conds in parts]
    seen = {tuple(sorted(ast.dump(c) for c in t)) for t in terms}
    merged = True
    while merged and not any(not t for t in terms):
        merged = False
        for i, a in enumerate(terms):
            for b in terms[i + 1:]:
                da, db = [ast.dump(c) for c in a], [ast.dump(c) for c in b]
                only_a = [c for c, d in zip(a, da) if d not in db]
                only_b = [c for c, d in zip(b, db) if d not in da]
                if len(only_a) == 1 and len(only_b) == 1 and _excludes(only_a[0], only_b[0]):
                    common = [c for c, d in zip(a, da) if d in db]
                    key = tuple(sorted(ast.dump(c) for c in common))
                    if key not in seen:
                        seen.add(key)
                        terms.append(common)
                        merged = True
                        break
            if merged:
                break
    return any(not t for t in terms)


def minted(fn: _Function, reference) -> bool:
    """A fresh id held in a name that the function also gives a tool call as its ``id``: it mints the call and its
    result together, and they pair."""
    if not isinstance(reference, ast.Name):
        return False
    for n in ast.walk(fn.node):
        if isinstance(n, ast.Call) and any(k.arg == "id" and isinstance(k.value, ast.Name) and k.value.id == reference.id for k in n.keywords):
            return True
        if isinstance(n, ast.Dict) and any(isinstance(k, ast.Constant) and k.value == "id" and isinstance(v, ast.Name) and v.id == reference.id
                                           for k, v in zip(n.keys, n.values)):
            return True
    return False


def pairing_facts(func, owner=None) -> tuple[list, list]:
    """``(answered in part, fresh call ids)`` in a step function and the functions of its package it calls.
    ``answered`` items are ``(function, iterated part, collection)``: the function builds tool messages for that part
    only. ``fresh`` items are ``(function, call-id expression)``."""
    answered, fresh = set(), set()
    seen: set = set()

    def package(f) -> str:
        return (getattr(f, "__module__", "") or "").rpartition(".")[0]

    home, home_module = package(func), getattr(func, "__module__", None)

    def visit(f, depth: int) -> None:
        f = getattr(f, "__func__", f)
        if id(f) in seen or depth > MAX_CALLS:
            return
        seen.add(id(f))
        node = _def(f)
        if node is None:
            return
        fn = _Function(f, node)
        by_collection: dict = {}
        for n in ast.walk(node):
            builds, reference = tool_message_reference(n)
            if builds:
                if reference is not None and fn.fresh(reference) and not minted(fn, reference):
                    fresh.add((f.__qualname__, ast.unparse(reference)))
                found = fn.answered(n, reference)
                if found is not None:
                    iterated, parts = found
                    for source, conds in parts:
                        by_collection.setdefault(source, {"iterated": iterated, "parts": []})["parts"].append((source, conds))
            if isinstance(n, ast.Call):
                if isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name) and n.func.value.id == "self" and owner is not None:
                    target = inspect.getattr_static(type(owner), n.func.attr, None)
                else:
                    target = fn.resolve(n.func)
                target = getattr(target, "__func__", target)
                if inspect.isfunction(target) and (package(target) == home or target.__module__ == home_module):
                    visit(target, depth + 1)
        for n in ast.walk(node):
            if isinstance(n, ast.Raise):
                found = fn.raised(n)
                if found is not None:
                    for source, conds in found[1]:
                        if source in by_collection:
                            by_collection[source]["parts"].append((source, conds))
        for source, entry in by_collection.items():
            if not _covered(entry["parts"]):
                answered.add((f.__qualname__, entry["iterated"], source))

    visit(func, 0)
    return sorted(answered), sorted(fresh)


def _plain(s: str) -> str:
    return " ".join(s.replace(",", " ").replace(":", " ").split())


def pairing_attrs(func, owner=None) -> dict:
    """The IR attributes of a step's pairing facts: ``unanswered_calls`` as ``<part>:<collection>`` items,
    ``unpaired_tool_ids`` as the functions that build tool messages with a fresh call id."""
    answered, fresh = pairing_facts(func, owner)
    attrs = {}
    if answered:
        attrs["unanswered_calls"] = ",".join(sorted({f"{_plain(part)}:{_plain(of)}" for _, part, of in answered}))
    if fresh:
        attrs["unpaired_tool_ids"] = ",".join(sorted({_plain(f) for f, _ in fresh}))
    return attrs
