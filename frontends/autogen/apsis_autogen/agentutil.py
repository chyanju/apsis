"""AutoGen introspection helpers shared by the 0.2 and 0.4 builders; they read live objects and class sources."""
from __future__ import annotations

import ast
import inspect
import re
import textwrap

_AGENT_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def _framework_version() -> str | None:
    for mod in ("autogen_agentchat", "autogen", "autogen_core"):
        try:
            m = __import__(mod)
            v = getattr(m, "__version__", None)
            if v:
                return v
        except Exception:
            continue
    return None


def _oid(obj) -> str:
    return hex(id(obj))


def _safe_name(obj, default: str) -> str:
    n = getattr(obj, "name", None)
    if isinstance(n, str) and n:
        return n
    n = getattr(obj, "_name", None)
    if isinstance(n, str) and n:
        return n
    return default


def _tn(obj) -> str:
    t = type(obj)
    return f"{t.__module__}.{t.__name__}"


def _bool_attr(obj, *names) -> bool | None:
    for n in names:
        if hasattr(obj, n):
            return bool(getattr(obj, n))
    return None


def _termination_repr(obj) -> str | None:
    """The class names of a termination condition, without its values."""
    if obj is None:
        return None
    t = type(obj).__name__
    # combined conditions (Or/And) keep their parts in _conditions
    parts = getattr(obj, "_conditions", None)
    if isinstance(parts, (list, tuple)) and parts:
        return " | ".join(_termination_repr(p) or type(p).__name__ for p in parts)
    return t


# --- 0.2 agent facts ---

def _reply_chain(agent) -> list[str]:
    return [
        getattr(d.get("reply_func"), "__name__", str(d.get("reply_func")))
        for d in (getattr(agent, "_reply_func_list", []) or [])
        if isinstance(d, dict)
    ]


def _llm_declared_functions(agent) -> list[str]:
    cfg = getattr(agent, "llm_config", None)
    names: list[str] = []
    if isinstance(cfg, dict):
        for f in cfg.get("functions", []) or []:
            if isinstance(f, dict) and f.get("name"):
                names.append(f["name"])
        for t in cfg.get("tools", []) or []:
            if isinstance(t, dict):
                fn = t.get("function", t)
                if isinstance(fn, dict) and fn.get("name"):
                    names.append(fn["name"])
    return names


def _function_map_keys(agent) -> list[str]:
    fm = getattr(agent, "_function_map", None) or getattr(agent, "function_map", None)
    return sorted(fm.keys()) if isinstance(fm, dict) else []


def _agent_role(agent, is_manager: bool) -> str | None:
    if is_manager:
        return "manager"
    tn = type(agent).__name__
    if "UserProxy" in tn:
        return "user"
    if "Assistant" in tn:
        return "assistant"
    return None


def _human_input(agent) -> str | None:
    hi = getattr(agent, "human_input_mode", None) or getattr(agent, "_human_input_mode", None)
    return hi if isinstance(hi, str) else None


# --- 0.4 agent facts and the agent-node builder ---

def _produced_message_types(agent) -> list[str]:
    pmt = getattr(agent, "produced_message_types", None)
    out = []
    if isinstance(pmt, (list, tuple)):
        for t in pmt:
            out.append(getattr(t, "__name__", str(t)))
    return out


def _produced_message_classes(agent) -> list:
    """``produced_message_types``, narrowed to what the handler can send when that is known and leaves some."""
    pmt = getattr(agent, "produced_message_types", None)
    declared = [t for t in pmt if isinstance(t, type)] if isinstance(pmt, (list, tuple)) else []
    sent = _sent_message_classes(agent)
    if sent is None:
        return declared
    return [t for t in declared if any(issubclass(c, t) for c in sent)] or declared


def _sent_message_classes(agent) -> list | None:
    """Classes ``C`` of the ``Response(chat_message=C(...))`` that ``on_messages_stream`` can produce, or None."""
    found: list = []
    complete = _collect_response_classes(type(agent), "on_messages_stream", agent, found, depth=0)
    return found if complete and found else None


def _collect_response_classes(cls, meth: str, agent, found: list, depth: int) -> bool:
    """Add the response classes of ``cls.meth`` to ``found``; False when some value cannot be read."""
    if depth > 2:
        return False
    fn = getattr(cls, meth, None)
    fn = getattr(fn, "__func__", fn)
    if fn is None:
        return False
    try:
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    except (OSError, TypeError, SyntaxError):
        return False
    top = next((n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))), None)
    if top is None:
        return False
    glb = getattr(fn, "__globals__", {}) or {}
    assigned: dict[str, list] = {}
    looped: dict[str, list] = {}
    for n in ast.walk(top):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    assigned.setdefault(t.id, []).append(n.value)
        elif isinstance(n, ast.AnnAssign) and n.value is not None and isinstance(n.target, ast.Name):
            assigned.setdefault(n.target.id, []).append(n.value)
        elif isinstance(n, (ast.For, ast.AsyncFor)) and isinstance(n.target, ast.Name):
            looped.setdefault(n.target.id, []).append(n.iter)

    def self_method(expr):
        """``m`` for ``self.m(...)``, awaited or not, else None."""
        if isinstance(expr, ast.Await):
            expr = expr.value
        if (isinstance(expr, ast.Call) and isinstance(expr.func, ast.Attribute)
                and isinstance(expr.func.value, ast.Name) and expr.func.value.id == "self"):
            return expr.func.attr
        return None

    def classify(v, seen: frozenset) -> bool:
        if isinstance(v, ast.Constant) and v.value is None:
            return True  # no response on this path
        if isinstance(v, ast.Call) and isinstance(v.func, ast.Name):
            called = glb.get(v.func.id)
            if v.func.id == "Response":
                arg = next((k.value for k in v.keywords if k.arg == "chat_message"), v.args[0] if v.args else None)
                c = glb.get(arg.func.id) if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name) else None
                if not inspect.isclass(c):
                    return False
                if c not in found:
                    found.append(c)
                return True
            return inspect.isclass(called)  # an inner event of another class
        m = self_method(v)
        if m is not None:
            return _collect_response_classes(cls, m, agent, found, depth + 1)
        if isinstance(v, ast.Name) and v.id not in seen:
            values = assigned.get(v.id, [])
            iters = looped.get(v.id, [])
            if not values and not iters:
                return False
            ok = all(classify(x, seen | {v.id}) for x in values)
            for it in iters:
                m = self_method(it)
                ok = ok and m is not None and _collect_response_classes(cls, m, agent, found, depth + 1)
            return ok
        return False

    complete = True
    for v in _reachable_values(top.body, agent):
        complete = classify(v, frozenset()) and complete
    return complete


def _reachable_values(stmts, agent, reachable: bool = True):
    """Values yielded or returned in ``stmts`` on paths a bool attribute of ``agent`` does not rule out."""
    for st in stmts:
        if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(st, ast.If):
            flag = _config_flag(st.test, agent)
            yield from _reachable_values(st.body, agent, reachable and flag is not False)
            yield from _reachable_values(st.orelse, agent, reachable and flag is not True)
            continue
        if isinstance(st, ast.Return):
            if reachable and st.value is not None:
                yield st.value
            continue
        nested = [getattr(st, f) for f in ("body", "orelse", "finalbody") if isinstance(getattr(st, f, None), list)]
        nested += [h.body for h in getattr(st, "handlers", None) or []]
        nested += [c.body for c in getattr(st, "cases", None) or []]
        if nested:
            for b in nested:
                yield from _reachable_values(b, agent, reachable)
            continue
        if reachable:
            for n in ast.walk(st):
                if isinstance(n, (ast.Yield, ast.YieldFrom)) and n.value is not None:
                    yield n.value


def _config_flag(test, agent) -> bool | None:
    """The value of a ``self.<attr>`` or ``not self.<attr>`` test of a bool attribute on ``agent``, else None."""
    negate = False
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        negate, test = True, test.operand
    if isinstance(test, ast.Attribute) and isinstance(test.value, ast.Name) and test.value.id == "self":
        value = getattr(agent, test.attr, None)
        if isinstance(value, bool):
            return (not value) if negate else value
    return None


def _accepted_message_classes(agent) -> list:
    """Element classes of the ``messages`` parameter of ``on_messages``, narrowed by a guard in the handler."""
    import typing

    fn = getattr(type(agent), "on_messages", None)
    if fn is None:
        return []
    try:
        ann = typing.get_type_hints(fn).get("messages")
    except Exception:
        return []
    args = typing.get_args(ann)
    if not args:
        return []
    declared = [m for m in (typing.get_args(args[0]) or (args[0],)) if isinstance(m, type)]
    guarded = _guarded_message_classes(type(agent))
    if guarded is None:
        return declared
    return [m for m in declared if any(issubclass(m, g) for g in guarded)] or guarded


def _guarded_message_classes(agent_cls) -> list | None:
    """Classes a guard in ``on_messages_stream`` or ``on_messages`` lets through, or None without a guard."""
    fns = []
    for meth in ("on_messages_stream", "on_messages"):
        fn = getattr(agent_cls, meth, None)
        fns.append(getattr(fn, "__func__", fn))
    return _guarded_classes(fns, lambda it: isinstance(it, ast.Name) and it.id == "messages")


def _thread_guarded_message_classes(manager_cls) -> list | None:
    """Classes a guard over ``self._message_thread`` in any method of the manager lets through, or None."""
    fns = []
    for cls in getattr(manager_cls, "__mro__", ()):
        if cls is object:
            continue
        fns.extend(v for v in vars(cls).values() if inspect.isfunction(v))

    def over_thread(it):
        return (isinstance(it, ast.Attribute) and it.attr == "_message_thread"
                and isinstance(it.value, ast.Name) and it.value.id == "self")

    return _guarded_classes(fns, over_thread)


def _guarded_classes(fns, over) -> list | None:
    found: list = []
    for fn in fns:
        if fn is None:
            continue
        try:
            tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
        except (OSError, TypeError, SyntaxError):
            continue
        names = _guard_class_names(tree, over)
        if names is None:
            continue
        glb = getattr(fn, "__globals__", {}) or {}
        classes = [glb.get(n) for n in names]
        if all(isinstance(c, type) for c in classes):
            found.extend(c for c in classes if c not in found)
    return found or None


def _guard_class_names(tree, over) -> list[str] | None:
    """Class names an ``isinstance`` assert or if-chain (ending in raise/assert) admits in a loop over ``over``."""
    for loop in ast.walk(tree):
        if not (isinstance(loop, (ast.For, ast.AsyncFor)) and over(loop.iter) and isinstance(loop.target, ast.Name)):
            continue
        var = loop.target.id
        if loop.body and isinstance(loop.body[0], ast.Assert):
            asserted = _asserted_class_names(loop.body[0].test, var)
            if asserted:
                return asserted
        for st in loop.body:
            if not isinstance(st, ast.If):
                continue
            names: list[str] = []
            typed = False
            node = st
            while True:
                test = node.test
                if _isinstance_of(test, var):
                    typed = True
                    names.extend(_class_names(test.args[1]))
                if len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
                    node = node.orelse[0]
                    continue
                final = node.orelse
                if typed and final and all(isinstance(s, ast.Raise) for s in final):
                    return names
                if final and isinstance(final[0], ast.Assert):
                    asserted = _asserted_class_names(final[0].test, var)
                    if asserted:
                        return names + asserted
                break
    return None


def _isinstance_of(test, var: str) -> bool:
    return (isinstance(test, ast.Call) and isinstance(test.func, ast.Name) and test.func.id == "isinstance"
            and len(test.args) == 2 and isinstance(test.args[0], ast.Name) and test.args[0].id == var)


def _asserted_class_names(test, var: str) -> list[str] | None:
    """The classes of ``assert isinstance(var, ...)``, or of an ``or`` of such tests."""
    if _isinstance_of(test, var):
        return _class_names(test.args[1])
    if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or) and all(_isinstance_of(v, var) for v in test.values):
        return [n for v in test.values for n in _class_names(v.args[1])]
    return None


def _class_names(expr) -> list[str]:
    """The class names of the second argument of ``isinstance``: a name, ``A | B`` or a tuple of them."""
    if isinstance(expr, ast.Name):
        return [expr.id]
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.BitOr):
        return _class_names(expr.left) + _class_names(expr.right)
    if isinstance(expr, ast.Tuple):
        return [n for e in expr.elts for n in _class_names(e)]
    return ["<unknown>"]


def _message_sockets(classes, *, inputs: bool) -> tuple[list[dict], dict[str, str]]:
    """Sockets for message classes and, for outputs, the ``supertypes:<T>`` facts (the bases of ``T``)."""
    sockets, supertypes = [], {}
    for t in classes:
        name = t.__name__
        if any(s["name"] == name for s in sockets):
            continue
        if inputs:
            sockets.append({"name": name, "type_repr": name, "mandatory": False})
        else:
            sockets.append({"name": name, "type_repr": name, "may_emit": True})
            bases = [b.__name__ for b in t.__mro__[1:] if b is not object]
            if bases:
                supertypes[f"supertypes:{name}"] = ", ".join(bases)
    return sockets, supertypes


def _agent_tools(agent) -> list[str]:
    for attr in ("_tools", "tools"):
        v = getattr(agent, attr, None)
        if isinstance(v, (list, tuple)) and v:
            names = []
            for t in v:
                nm = getattr(t, "name", None) or getattr(t, "__name__", None) or type(t).__name__
                names.append(nm)
            return names
    return []


def _handoff_targets(agent) -> list[str]:
    h = getattr(agent, "_handoffs", None) or getattr(agent, "handoffs", None)
    targets: list[str] = []
    if isinstance(h, dict):
        for k, v in h.items():
            t = getattr(v, "target", None)
            targets.append(t if isinstance(t, str) else str(k))
    elif isinstance(h, (list, tuple)):
        for item in h:
            t = getattr(item, "target", None)
            targets.append(t if isinstance(t, str) else (item if isinstance(item, str) else str(item)))
    return targets


def _agent_node_v04(agent) -> dict:
    nm = _safe_name(agent, _tn(agent))
    attrs: dict[str, str] = {}
    tools = _agent_tools(agent)
    if tools:
        attrs["tools"] = ",".join(tools)
    reflect = _bool_attr(agent, "_reflect_on_tool_use", "reflect_on_tool_use")
    if reflect is not None:
        attrs["reflect_on_tool_use"] = str(reflect)
    pmt = _produced_message_types(agent)
    if pmt:
        attrs["produced_message_types"] = ",".join(pmt)
    # GraphFlow MessageFilterAgent
    wrapped = getattr(agent, "_wrapped_agent", None) or getattr(agent, "wrapped_agent", None)
    if wrapped is not None:
        attrs["wraps"] = _safe_name(wrapped, _tn(wrapped))
    kind = "agent"
    tn = type(agent).__name__
    if "UserProxy" in tn:
        kind = "human-input"
    handoffs = _handoff_targets(agent)
    inputs, _ = _message_sockets(_accepted_message_classes(agent), inputs=True)
    outputs, supertypes = _message_sockets(_produced_message_classes(agent), inputs=False)
    attrs.update(supertypes)
    return {
        "id": nm, "type_name": _tn(agent), "kind": kind, "name": nm,
        "role": _agent_role(agent, False),
        "declared_targets": handoffs,
        "instance_id": _shared_state_instance_id(agent),
        "inputs": inputs,
        "outputs": outputs,
        "attrs": attrs,
    }


def _shared_state_instance_id(agent) -> str:
    """The id of the agent's model context (agents sharing one alias state), else of the agent."""
    ctx = getattr(agent, "_model_context", None) or getattr(agent, "model_context", None)
    if ctx is not None:
        return _oid(ctx)
    return _oid(agent)


# --- autogen-core pub/sub ---

def _agent_publishes(agent_cls, instance=None) -> tuple[set[str], bool] | None:
    """``(topic types, publishes on ctx.topic_id)`` of the class's ``publish_message`` calls; None without source."""
    try:
        tree = ast.parse(textwrap.dedent(inspect.getsource(agent_cls)))
    except (OSError, TypeError, SyntaxError):
        return None
    topics: set[str] = set()
    on_arrival_topic = False
    for call in ast.walk(tree):
        if not (isinstance(call, ast.Call) and _called_name(call) == "publish_message"):
            continue
        topic = _argument(call, 1, "topic_id")
        if isinstance(topic, ast.Attribute) and topic.attr == "topic_id":
            on_arrival_topic = True
        else:
            topics.add(_topic_type(topic, instance) or "default")
    return topics, on_arrival_topic


def _called_name(call: ast.Call) -> str | None:
    f = call.func
    if isinstance(f, ast.Attribute):
        return f.attr
    return f.id if isinstance(f, ast.Name) else None


def _argument(call: ast.Call, position: int, keyword: str):
    if len(call.args) > position:
        return call.args[position]
    return next((k.value for k in call.keywords if k.arg == keyword), None)


def _topic_type(expr, instance=None) -> str | None:
    """The topic type a ``DefaultTopicId(...)`` or ``TopicId(...)`` expression names, if readable."""
    if not (isinstance(expr, ast.Call) and _called_name(expr) in ("DefaultTopicId", "TopicId")):
        return None
    t = _argument(expr, 0, "type")
    if t is None:
        return "default" if _called_name(expr) == "DefaultTopicId" else None
    if isinstance(t, ast.Constant) and isinstance(t.value, str):
        return t.value
    if instance is not None and isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self":
        value = getattr(instance, t.attr, None)
        return value if isinstance(value, str) else None
    return None


def _wrap(nodes, edges, channels, provenance, start_nodes, output_nodes) -> dict:
    return {
        "execution_model": "group-chat-speaker",
        "framework": "autogen",
        "framework_version": _framework_version(),
        "provenance": provenance,
        "nodes": nodes,
        "edges": edges,
        "channels": channels,
        "start_nodes": start_nodes,
        "output_nodes": output_nodes,
    }
