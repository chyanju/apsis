"""Tests of the front-ends that need no framework installed: python3 -m unittest discover -s frontends/tests"""
import functools
import json
import os
import sys
import tempfile
import types
import unittest
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
for package in ("common", "langflow", "flowise", "langgraph", "agent-framework", "autogen", "crewai", "llamaindex", "parlant", "pydantic-ai"):
    sys.path.insert(0, os.path.join(HERE, "..", package))

from apsis_flowise.extract import extract as flowise_extract  # noqa: E402
from apsis_flowise.load import get_flow  # noqa: E402
from apsis_langflow.extract import extract as langflow_extract  # noqa: E402
from apsis_langflow.load import load_flow  # noqa: E402
from apsis_langflow.nodekind import _node_kind  # noqa: E402
from apsis_langflow.subflow import _run_flow_output_bindings  # noqa: E402
from apsis_agent_framework.channels import _shared_state  # noqa: E402
from apsis_agent_framework.load import SHARED, _resolve  # noqa: E402
from apsis_agent_framework.nodes import _host_yields  # noqa: E402
from apsis_autogen.agentutil import _agent_publishes, _message_sockets  # noqa: E402
from apsis_crewai.extract import _accepted, _value_type  # noqa: E402
from apsis_llamaindex.extract import _implicit_waits, _sent  # noqa: E402
from apsis_parlant.extract import extract as parlant_extract  # noqa: E402
from apsis_langgraph.host import host_workflow  # noqa: E402
from apsis_langgraph.load import _checkpoint  # noqa: E402
from apsis_langgraph.schema import _reducer_of  # noqa: E402
from apsis_pydantic_ai.changes import changes as pydantic_ai_changes  # noqa: E402
from apsis_common.toolcalls import pairing_facts  # noqa: E402
from apsis_pydantic_ai.extract import _shared as pydantic_ai_shared  # noqa: E402
from apsis_langgraph.astutil import (  # noqa: E402
    _ast_command_send_targets,
    _fixed_calls,
    _missing_keys,
    _node_func,
    _node_source_ast,
    _required_run_inputs,
    _rewrap_resets,
    _router_return_targets,
    _single_pass_writes,
)


def written(obj) -> str:
    """Write `obj` as JSON to a temporary file and return its path."""
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(obj, f)
    f.close()
    return f.name


class CrewAIModelFields(unittest.TestCase):
    def test_a_model_field_takes_its_own_types_as_they_are(self):
        import typing

        class BaseLLM:
            pass

        class ProviderLLM(BaseLLM):
            pass

        accepted = _accepted(typing.Union[str, typing.Annotated[BaseLLM, "instance"], typing.Any, None])
        self.assertEqual(accepted, [str, BaseLLM])
        self.assertTrue(_value_type(ProviderLLM(), accepted).endswith(".BaseLLM"))
        self.assertEqual(_value_type("gpt-4o-mini", accepted), "str")
        self.assertEqual(_value_type(3, accepted), "int")


class ResponseEvent:
    pass


class ToolCallEvent:
    pass


async def _waits(ctx):
    await ctx.wait_for_event(ResponseEvent)
    await ctx.wait_for_event(ResponseEvent, waiter_id="mine")


async def _fans_out(ctx, calls):
    for _ in calls:
        ctx.send_event(ToolCallEvent())
    ctx.send_event(ResponseEvent())


class LlamaIndexStepFacts(unittest.TestCase):
    def test_a_wait_without_a_waiter_id_is_implicit(self):
        self.assertEqual(_implicit_waits(_waits), [ResponseEvent])

    def test_events_sent_in_a_loop_are_a_fan_out(self):
        self.assertEqual(set(_sent(_fans_out)), {(ToolCallEvent, True), (ResponseEvent, False)})


class Book:
    def __init__(self):
        self._items = {}

    def add(self, key, value):
        self._items[key] = value

    def get(self, key):
        return self._items.get(key)


def _records(ctx, key: str):
    book = ctx.deps.book
    book.add(key, 1)
    book.get(key)
    ctx.deps.log.append(key)
    ctx.deps.calls += 1


class PydanticAIToolChanges(unittest.TestCase):
    def test_a_started_run_that_changes_what_it_shares_with_the_run_that_started_it(self):
        ns = types.SimpleNamespace
        tool = ns(function=_records, takes_ctx=True)
        book = Book()
        parent = ns(book=book, log=[], calls=0)
        child = ns(book=book, log=[], calls=0)
        found = pydantic_ai_changes(tool, child)
        self.assertEqual(found, {("book", "_items", "[]"), ("log", "append()"), ("calls",)})
        run = ns(deps=child, parent=ns(deps=parent))
        # the book is the parent's; the log and the counter are the child's own
        self.assertEqual({c: pydantic_ai_shared(c, run) is not None for c in found},
                         {("book", "_items", "[]"): True, ("log", "append()"): False, ("calls",): False})
        # a run handed the deps object itself shares every field of it
        self.assertIs(pydantic_ai_shared(("calls",), ns(deps=parent, parent=ns(deps=parent))), parent)


class BaseChannel:
    pass


class DeltaChannel(BaseChannel):
    def __init__(self, reducer):
        self.reducer = reducer


class LastValue(BaseChannel):
    pass


def add_messages(left, right):
    return left + right


class Command:
    def __init__(self, resume=None):
        self.resume = resume


class Producer:
    def __init__(self):
        self._agent = None
        self._current = None

    def agent(self):
        if self._agent is None:
            self._agent = object()
        return self._agent

    async def start(self, message, thread_id=None):
        self._current = thread_id
        return await self.agent().ainvoke({"messages": [message]}, config={"configurable": {"thread_id": thread_id}})

    async def resume(self, decisions, thread_id=None):
        thread_id = thread_id or self._current
        config = {"configurable": {"thread_id": thread_id}}
        return await self.agent().ainvoke(Command(resume=decisions), config=config)


class Memory:
    async def aretain(self, **kwargs):
        return None


def memory_tools(bank_id, client):
    async def retain(content: str) -> str:
        kwargs = {"bank_id": bank_id, "content": content}
        await client.aretain(**kwargs)
        return "stored"

    async def retain_for_run(content: str, config) -> str:
        await client.aretain(bank_id=config["configurable"]["user_id"], content=content)
        return "stored"

    return retain, retain_for_run


class Editor:
    def __init__(self):
        def file_tool(command: str, path: str, new_path: str | None = None):
            args = {"path": path}
            if new_path is not None:
                args["new_path"] = new_path
            if command == "view":
                return self._handle_view(args)
            return self._handle_rename(args)

        self.tool = file_tool

    def _handle_view(self, args):
        return args["path"]

    def _handle_rename(self, args):
        return args["old_path"], args["new_path"], args.get("mode")


class Wrapper:
    def __init__(self, bound=None, carry=False):
        self.bound = bound
        self.carry = carry
        object.__setattr__(self, "_failures", 0)

    def with_config(self, config):
        rebound = type(self)(self.bound, self.carry)
        if self.carry:
            object.__setattr__(rebound, "_failures", self._failures)
        return rebound

    def fail(self):
        n = int(getattr(self, "_failures", 0)) + 1
        object.__setattr__(self, "_failures", n)


def dispatcher(agents):
    def task(name: str):
        return agents[name].fail()

    return task


class ToolMessage:
    def __init__(self, content, tool_call_id):
        self.content, self.tool_call_id = content, tool_call_id


def answer_one_part(results, frontend):
    backend = [r for r in results if r.name not in frontend]
    messages = []
    for r in backend:
        messages.append(ToolMessage(content=r.output, tool_call_id=r.call_id))
    return messages


def answer_both_parts(results, frontend):
    backend = [r for r in results if r.name not in frontend]
    browser = [r for r in results if r.name in frontend]
    return [ToolMessage(content=r.output, tool_call_id=r.call_id) for r in [*backend, *browser]]


def answer_known_tools(calls, tools):
    out = []
    for call in calls:
        if call["name"] in tools:
            out.append(ToolMessage(content="done", tool_call_id=call["id"]))
        else:
            out.append(ToolMessage(content="unknown tool", tool_call_id=call["id"]))
    return out


def as_wire_message(message):
    return {"role": "tool", "content": message.content, "tool_call_id": message.extra.get("tool_call_id", str(uuid.uuid4()))}


def call_with_its_result():
    call_id = str(uuid.uuid4())
    return {"id": call_id, "name": "lookup", "args": {}}, ToolMessage(content="ok", tool_call_id=call_id)


def trim_in_loop(state):
    removed = []
    for msg in state["messages"][:3]:
        removed.append(msg)
        return {"messages": removed}


def trim_after_loop(state):
    removed = []
    for msg in state["messages"][:3]:
        removed.append(msg)
    return {"messages": removed}


def first_match(state):
    for msg in state["messages"]:
        return {"last": msg}


class ReadsAnUpdateReturnedFromInsideALoop(unittest.TestCase):
    def test_the_loop_returns_after_its_first_item(self):
        self.assertEqual(_single_pass_writes(trim_in_loop), ["messages"])
        self.assertEqual(_single_pass_writes(trim_after_loop), [])
        # a loop that only returns its first item builds nothing per item
        self.assertEqual(_single_pass_writes(first_match), [])


class ReadsHowToolMessagesPairWithCalls(unittest.TestCase):
    def test_tool_messages_for_a_part_picked_by_a_condition(self):
        self.assertEqual(pairing_facts(answer_one_part), ([("answer_one_part", "backend", "results")], []))

    def test_parts_whose_conditions_cover_every_call(self):
        self.assertEqual(pairing_facts(answer_both_parts), ([], []))
        self.assertEqual(pairing_facts(answer_known_tools), ([], []))

    def test_a_call_id_that_is_a_fresh_value(self):
        answered, fresh = pairing_facts(as_wire_message)
        self.assertEqual((answered, [f for f, _ in fresh]), ([], ["as_wire_message"]))
        # a fresh id minted for a call and its result together pairs
        self.assertEqual(pairing_facts(call_with_its_result), ([], []))


class ReadsTheCountersARewrapResets(unittest.TestCase):
    def test_a_count_kept_on_the_instance_that_with_config_drops(self):
        self.assertEqual(_rewrap_resets(dispatcher({"recon": Wrapper()})), ["Wrapper._failures"])
        self.assertEqual(_rewrap_resets(dispatcher({"recon": Wrapper(carry=True)})), [])


def get_config():
    return {}


def _needs_thread(state, runtime):
    context = runtime.context or {}
    thread_id = context.get("thread_id")
    if thread_id is None:
        config = get_config()
        thread_id = config.get("configurable", {}).get("thread_id")
    if thread_id is None:
        raise ValueError("Thread ID is required")
    user = context.get("user_id")
    return {"thread": thread_id, "user": user}


class ReadsTheRunInputsAStepNeeds(unittest.TestCase):
    def test_a_key_of_the_context_or_the_configurable_whose_absence_raises(self):
        # `user_id` is read too, but its absence raises nothing
        self.assertEqual(_required_run_inputs(_needs_thread), ["thread_id"])


class ReadsTheKeysAToolsDictLacks(unittest.TestCase):
    def test_a_key_the_method_reads_and_the_tool_never_sets(self):
        self.assertEqual(_missing_keys(Editor().tool), ["_handle_rename.old_path"])


class ReadsTheFixedCallsOfATool(unittest.TestCase):
    def test_a_tool_that_reads_no_run_config_calls_with_values_captured_at_build(self):
        retain, retain_for_run = memory_tools("user-123", Memory())
        self.assertEqual(_fixed_calls(retain), ["aretain.bank_id=user-123"])
        self.assertEqual(_fixed_calls(retain_for_run), [])


class ReadsTheHostOfRuns(unittest.TestCase):
    def test_the_methods_that_start_and_resume_runs_and_the_fields_they_use(self):
        host = Producer()
        steps = {n["id"]: n["attrs"] for n in host_workflow(host, {})["nodes"]}
        ident = f"Producer@{hex(id(host))}"
        # `agent` starts no run, and the field it sets once is an initialization
        self.assertEqual(steps, {
            "resume": {"resume_thread": f"_current:{ident}"},
            "start": {"starts_runs": "true", "sets": f"_current:{ident}"},
        })


class ReadsTheCheckpointOfARun(unittest.TestCase):
    def test_sqlite_savers_on_one_file_are_one_checkpoint_store(self):
        import sqlite3

        ns = types.SimpleNamespace
        with tempfile.TemporaryDirectory() as d:
            conns = [sqlite3.connect(os.path.join(d, "NVDA.db")) for _ in range(2)]
            try:
                runs = [_checkpoint(ns(checkpointer=ns(conn=c)), {"configurable": {"thread_id": "41fd"}}) for c in conns]
                self.assertEqual(runs[0], runs[1])
                self.assertTrue(runs[0].endswith("NVDA.db#41fd"))
                self.assertIsNone(_checkpoint(ns(checkpointer=ns(conn=conns[0])), None))
                self.assertIsNone(_checkpoint(ns(checkpointer=None), {"configurable": {"thread_id": "41fd"}}))
            finally:
                for c in conns:
                    c.close()


class ReadsTheReducerOfAStateField(unittest.TestCase):
    def test_a_channel_object_in_the_metadata_gives_its_reducer_and_required_is_looked_through(self):
        from typing import Annotated, Required

        self.assertEqual(_reducer_of(Required[Annotated[list, DeltaChannel(add_messages)]]), ({"messages": None}, "list"))
        self.assertEqual(_reducer_of(Annotated[int, LastValue()]), (None, "int"))
        self.assertEqual(_reducer_of(Annotated[list, LastValue]), (None, "list"))
        self.assertEqual(_reducer_of(Required[int]), (None, "int"))


class ParlantJourneys(unittest.TestCase):
    def test_a_transition_into_another_journey_names_that_journey_state(self):
        ns = types.SimpleNamespace

        def journey(jid, title, root, nodes, edges):
            return (ns(id=jid, title=title, root_id=root),
                    [ns(id=n, action=n, description="") for n in nodes],
                    [ns(source=a, target=b, condition=c) for a, b, c in edges])

        ir = parlant_extract([
            journey("j1", "Journey One", "r1", ["r1", "end"], [("r1", "x2", "jump")]),
            journey("j2", "Journey Two", "r2", ["r2", "x2", "end"], [("r2", "x2", None), ("x2", "end", None)]),
        ], {})
        one, two = ir["workflows"]
        self.assertEqual(one["attrs"], {"self_contained": "true"})
        self.assertEqual([(e["from"]["node"], e["to"]["node"]) for e in one["edges"]],
                         [("__start__", "journey-one/root"), ("journey-one/root", "journey-two/s1")])
        self.assertEqual([(e["from"]["node"], e["to"]["node"]) for e in two["edges"]][-1], ("journey-two/s1", "__end__"))


class RejectsWhatIsNotAFlow(unittest.TestCase):
    def check(self, load, obj):
        path = written(obj)
        try:
            with self.assertRaises(ValueError):
                load(path)
        finally:
            os.unlink(path)

    def test_langflow(self):
        for obj in ({"name": "no data"}, {"data": {"edges": []}}, {"data": {"nodes": []}}, ["a", "list"]):
            self.check(load_flow, obj)

    def test_flowise(self):
        for obj in ({"name": "no nodes"}, {"nodes": "x"}, {"nodes": [], "edges": []}, ["a", "list"]):
            self.check(get_flow, obj)


class ExtractsAMinimalFlow(unittest.TestCase):
    def test_langflow_router_branches(self):
        def node(node_id, comp_type, outputs):
            return {"id": node_id, "data": {"type": comp_type, "node": {"template": {}, "outputs": [{"name": o} for o in outputs]}}}

        def edge(source, handle, target):
            return {"source": source, "target": target,
                    "data": {"sourceHandle": {"name": handle}, "targetHandle": {"fieldName": "input_value"}}}

        flow = {"data": {
            "nodes": [node("in", "ChatInput", ["message"]), node("r", "ConditionalRouter", ["true_result", "false_result"]),
                      node("out", "ChatOutput", ["message"])],
            "edges": [edge("in", "message", "r"), edge("r", "true_result", "out")],
        }}
        ir = langflow_extract(flow, {"kind": "test"})
        self.assertEqual(ir["execution_model"], "visual-dataflow")
        kinds = {n["id"]: n["kind"] for n in ir["nodes"]}
        self.assertEqual(kinds["r"], "router")
        router = next(n for n in ir["nodes"] if n["id"] == "r")
        self.assertEqual(router["attrs"]["branch_outputs"], "data-gate")
        branch = next(e for e in ir["edges"] if e["from"]["node"] == "r")
        self.assertEqual((branch["kind"], branch["branch"]), ("conditional", "true_result"))
        self.assertEqual(next(n for n in ir["nodes"] if n["id"] == "out")["attrs"]["accepts_stream"], "true")

    def test_langflow_scheduling_facts_follow_the_release(self):
        def node(node_id, comp_type, outputs, loop=False):
            return {"id": node_id, "data": {"type": comp_type, "node": {"template": {}, "outputs": [
                {"name": o, "allows_loop": loop and o == "item"} for o in outputs]}}}

        def edge(source, handle, target, field):
            return {"source": source, "target": target,
                    "data": {"sourceHandle": {"name": handle}, "targetHandle": {"fieldName": field}}}

        def facts(version):
            flow = {"data": {
                "nodes": [node("src", "URL", ["data"]), node("loop", "Loop", ["item", "done"], loop=True),
                          node("body", "Prompt", ["prompt"]), node("out", "ChatOutput", ["message"])],
                "edges": [edge("src", "data", "loop", "data"), edge("loop", "item", "body", "context"),
                          edge("body", "prompt", "loop", "item"), edge("loop", "done", "out", "input_value")],
            }}
            if version is not None:
                flow["last_tested_version"] = version
            ir = langflow_extract(flow, {"kind": "test"})
            return {n["id"]: {k: v for k, v in n.get("attrs", {}).items() if k in ("activation", "eager_start")}
                    for n in ir["nodes"]}

        # 1.0.x: every vertex waits for all its predecessors, on a cycle as well
        self.assertEqual(facts("1.0.19")["loop"], {"activation": "all"})
        # 1.1.x: a vertex on a cycle starts eagerly, one off it waits for all its predecessors
        self.assertEqual(facts("1.1.1")["body"], {"eager_start": "true"})
        self.assertEqual(facts("1.1.1")["out"], {"activation": "all"})
        # 1.2.0 to 1.4.x: only a loop starts eagerly
        self.assertEqual((facts("1.4.1")["loop"], facts("1.4.1")["body"]), ({"eager_start": "true"}, {}))
        # 1.5.0 makes a loop wait for its seed; from 1.10.1 a merge of exclusive branches runs on the branch taken
        self.assertEqual(facts("1.5.0")["loop"], {})
        self.assertEqual((facts("1.10.0")["out"], facts("1.10.1")["out"]), ({"activation": "all"}, {}))
        # an unknown release gets the facts of every release that could apply
        self.assertEqual(facts(None)["loop"], {"activation": "all", "eager_start": "true"})

    def test_langflow_run_flow_outputs_by_release(self):
        sub = {"data": {"nodes": [{"id": "ChatOutput-x", "data": {"node": {"outputs": [
            {"name": "message", "types": ["Message"]}]}}}]}}

        def bindings(method, version):
            node_def = {"outputs": [{"name": "out", "method": method}]}
            return [(b["inner"]["node"], b["inner"]["socket"], b.get("converted", False))
                    for b in _run_flow_output_bindings(node_def, "run", sub, version)]

        # 1.0.x: every result of the output vertices, a Message passed on as it is
        self.assertEqual(bindings("generate_results", "1.0.19"), [("ChatOutput-x", "message", False)])
        # 1.1.2 to 1.4.1: the result named `message` of the first output vertex, converted to the output's type
        self.assertEqual(bindings("data_output", "1.4.1"), [("ChatOutput-x", "message", True)])
        # from 1.4.2 the first result whatever its name; an unknown release may still need `message`
        self.assertEqual((bindings("data_output", "1.4.2"), bindings("data_output", None)),
                         ([], [("ChatOutput-x", "message", True)]))

    def test_langflow_model_picker_and_hidden_fields(self):
        template = {
            "model": {"type": "model", "required": True, "input_types": ["LanguageModel"], "show": True, "value": ""},
            "input_df": {"type": "other", "required": True, "input_types": ["DataFrame"], "show": False},
            "tools": {"type": "other", "required": True, "input_types": ["Tool"], "show": True},
        }
        flow = {"data": {"nodes": [{"id": "a", "data": {"type": "Agent", "node": {"template": template, "outputs": []}}}],
                         "edges": []}}
        socks = {s["name"]: s for s in langflow_extract(flow, {"kind": "test"})["nodes"][0]["inputs"]}
        self.assertFalse(socks["model"]["connection_only"])  # a model chosen in the picker needs no edge
        self.assertFalse(socks["input_df"]["mandatory"])  # a hidden field takes no value
        self.assertTrue(socks["tools"]["mandatory"] and socks["tools"]["connection_only"])

    def test_flowise_required_anchor(self):
        flow = {"nodes": [{"id": "chain_0", "data": {
            "name": "llmChain", "category": "Chains",
            "inputAnchors": [{"name": "model", "type": "BaseLanguageModel"}],
            "inputParams": [{"name": "chainName", "type": "string", "optional": True}],
            "outputAnchors": [{"id": "chain_0-output-llmChain-LLMChain", "name": "llmChain", "type": "LLMChain"}],
            "inputs": {},
        }}], "edges": []}
        ir = flowise_extract(flow, {"kind": "test"})
        model = next(s for s in ir["nodes"][0]["inputs"] if s["name"] == "model")
        self.assertTrue(model["mandatory"] and model["connection_only"])

    def test_flowise_sequential_node_inherits_its_model(self):
        flow = {"nodes": [{"id": "seqAgent_0", "data": {
            "name": "seqAgent", "category": "Sequential Agents",
            "inputAnchors": [{"name": "model", "type": "BaseChatModel"}], "inputs": {},
        }}], "edges": []}
        ir = flowise_extract(flow, {"kind": "test"})
        model = next(s for s in ir["nodes"][0]["inputs"] if s["name"] == "model")
        self.assertFalse(model["mandatory"])

    def test_flowise_condition_node_takes_every_in_edge_as_a_flow_edge(self):
        def seq_node(node_id, name):
            return {"id": node_id, "data": {
                "name": name, "category": "Sequential Agents",
                "inputAnchors": [{"name": "sequentialNode", "type": "Start | Agent | LLMNode"},
                                 {"name": "model", "type": "BaseChatModel"}], "inputs": {}}}

        def edge(source, target, anchor, ty):
            return {"source": source, "target": target, "sourceHandle": f"{source}-output-x-{ty}",
                    "targetHandle": f"{target}-input-{anchor}-{ty}"}

        model = {"id": "chatOpenAI_0", "data": {"name": "chatOpenAI", "category": "Chat Models", "inputAnchors": [],
                                                "outputAnchors": [{"id": "chatOpenAI_0-output-chatOpenAI-ChatOpenAI",
                                                                   "name": "chatOpenAI", "type": "ChatOpenAI"}],
                                                "inputs": {}}}
        flow = {"nodes": [model, seq_node("seqConditionAgent_0", "seqConditionAgent"), seq_node("seqAgent_0", "seqAgent")],
                "edges": [edge("chatOpenAI_0", "seqConditionAgent_0", "model", "BaseChatModel"),
                          edge("chatOpenAI_0", "seqAgent_0", "model", "BaseChatModel")]}
        ir = flowise_extract(flow, {"kind": "test"})
        into_flow = {e["to"]["node"] for e in ir["edges"]
                     if e["from"]["node"] == "chatOpenAI_0" and e["to"]["socket"] == "sequentialNode"}
        # the engine adds a graph edge from the model to the condition node, not to the agent
        self.assertEqual(into_flow, {"seqConditionAgent_0"})


def body(state):
    return {"x": 1}


class CallableBody:
    def __call__(self, state):
        return {"x": 1}


class ReadsTheSourceOfANodeBody(unittest.TestCase):
    def test_function_partial_and_callable_object(self):
        for func in (body, functools.partial(body), CallableBody()):
            self.assertIsNotNone(_node_source_ast(func))

    def test_builtin_has_no_source(self):
        self.assertIsNone(_node_source_ast(len))


class ToolStep:
    def func(self, state):
        return {"messages": []}


class RunnableWithFallbacks:
    """Like langchain-core's class: a forwarded lookup fails on an annotation imported only for type checking."""

    def __init__(self, runnable):
        self.runnable = runnable

    def __getattr__(self, name):
        raise NameError("name 'Runtime' is not defined")


class ReadsTheNodeFunctionOfARunnableWithFallbacks(unittest.TestCase):
    def test_the_primary_runnable_is_read(self):
        primary = ToolStep()
        spec = types.SimpleNamespace(runnable=RunnableWithFallbacks(primary))
        self.assertEqual(_node_func(spec), primary.func)


def Command(**kwargs):  # the routing objects of LangGraph, which the front-end reads by name
    return kwargs


Command.PARENT = "__parent__"


def Send(node, arg):
    return node, arg


def handoff_to(agent_name):
    def handoff(state):
        return Command(goto=[Send(agent_name, state)], graph=Command.PARENT)
    return handoff


def hand_off_by_keyword(state):
    return Command(goto=Send(node="billing", arg=state))


def fan_out_by_keyword(state):
    return [Send(node="worker", arg=item) for item in state["items"]]


def fan_out_to_a_computed_step(state):
    return [Send(state["next"], item) for item in state["items"]]


class ReadsTheTargetOfASend(unittest.TestCase):
    def test_a_send_in_a_goto_names_its_target(self):
        targets, uses_parent, has_send, unresolved = _ast_command_send_targets(handoff_to("research_agent"))
        self.assertEqual((targets, uses_parent, has_send, unresolved), (["research_agent"], True, True, False))

    def test_a_send_names_its_target_by_keyword(self):
        self.assertEqual(_ast_command_send_targets(hand_off_by_keyword), (["billing"], False, True, False))
        self.assertEqual(_router_return_targets(fan_out_by_keyword)["sends"], ["worker"])

    def test_a_routing_function_whose_send_target_is_computed_is_unresolved(self):
        self.assertTrue(_router_return_targets(fan_out_to_a_computed_step)["unresolved"])


COUNT = "count"


class Counter:
    async def handle(self, message, ctx):
        await ctx.set_state(COUNT, (await ctx.get_state(COUNT)) + 1)


class Seeder:
    async def handle(self, message, ctx):
        await ctx.set_state(COUNT, 0)
        return await ctx.get_state(COUNT)


class ReadsTheSharedStateOfAnAgentFrameworkExecutor(unittest.TestCase):
    def test_the_read_inside_a_write_comes_first(self):
        workflow = types.SimpleNamespace(executors={"counter": Counter(), "seeder": Seeder()})
        channels, reads_first = _shared_state(workflow)
        self.assertEqual(
            channels,
            [{"name": "count", "type_repr": "Any", "reducer": "last-value", "writers": ["counter", "seeder"], "readers": ["counter", "seeder"]}],
        )
        self.assertEqual(reads_first, {"counter": ["count"]})


class Ingest:
    async def handle(self, batch, ctx):
        await ctx.set_state(f"request_{batch.batch_id}", batch)


class Aggregate:
    async def handle(self, batch_id, ctx):
        return await ctx.get_state(f"request_{batch_id}")


class Lookup:
    async def handle(self, message, ctx):
        return await ctx.get_state("request_batch_5")


class Anywhere:
    async def handle(self, message, ctx):
        await ctx.set_state(message.key, message)


class NamesAStateKeyByItsSpelling(unittest.TestCase):
    def channels(self, **executors):
        channels, _ = _shared_state(types.SimpleNamespace(executors=executors))
        return {c["name"]: (c["writers"], c["readers"]) for c in channels}

    def test_keys_spelled_differently_are_different_channels(self):
        self.assertEqual(
            self.channels(ingest=Ingest(), aggregate=Aggregate(), lookup=Lookup()),
            {"request_{?}": (["ingest"], []), "request_{batch_id}": ([], ["aggregate"]), "request_batch_5": ([], ["lookup"])},
        )

    def test_a_write_to_a_key_the_source_does_not_name_writes_no_channel(self):
        self.assertEqual(self.channels(anywhere=Anywhere(), lookup=Lookup()), {"request_batch_5": ([], ["lookup"])})


class ChatMessage:
    pass


class TextMessage(ChatMessage):
    pass


class WritesTheMessageTypesOfAnAgentChatAgent(unittest.TestCase):
    def test_a_produced_type_is_an_output_with_its_base_classes(self):
        outputs, supertypes = _message_sockets([TextMessage, TextMessage], inputs=False)
        self.assertEqual(outputs, [{"name": "TextMessage", "type_repr": "TextMessage", "may_emit": True}])
        self.assertEqual(supertypes, {"supertypes:TextMessage": "ChatMessage"})

    def test_an_accepted_type_is_an_input(self):
        inputs, supertypes = _message_sockets([ChatMessage], inputs=True)
        self.assertEqual(inputs, [{"name": "ChatMessage", "type_repr": "ChatMessage", "mandatory": False}])
        self.assertEqual(supertypes, {})


def DefaultTopicId(type="default", source=None):  # the topic ids of autogen-core, which the front-end reads by name
    return type, source


def TopicId(type, source):
    return type, source


class Publisher:
    async def to_default(self, message, ctx):
        await self.publish_message(message, DefaultTopicId())

    async def to_review(self, message, ctx):
        await self.publish_message(message, TopicId("review", "publisher"))

    async def to_draft(self, message, ctx):
        await self.publish_message(message, topic_id=DefaultTopicId(type="draft"))


class Quiet:
    async def handle(self, message, ctx):
        # replies instead of calling self.publish_message(message, TopicId("review", "quiet"))
        return "publish_message"


class Relay:
    def __init__(self, topic_type):
        self._topic_type = topic_type

    async def handle(self, message, ctx):
        await self.publish_message(message, DefaultTopicId(type=self._topic_type))
        await self.publish_message(message, ctx.topic_id)


class ReadsTheTopicsAnAutoGenAgentPublishesTo(unittest.TestCase):
    def test_the_topic_of_each_publish_call(self):
        self.assertEqual(_agent_publishes(Publisher), ({"default", "review", "draft"}, False))

    def test_a_comment_or_a_string_is_not_a_call(self):
        self.assertEqual(_agent_publishes(Quiet), (set(), False))

    def test_a_topic_held_by_the_agent_and_the_topic_a_message_arrived_on(self):
        self.assertEqual(_agent_publishes(Relay, Relay("summary")), ({"summary"}, True))
        # without an instance the topic type is not known
        self.assertEqual(_agent_publishes(Relay), ({"default"}, True))


class ClassifiesALangflowComponentByTheWordsOfItsClassName(unittest.TestCase):
    def test_whole_words(self):
        kinds = {t: _node_kind(t, {}, {}) for t in (
            "ConditionalRouter", "OpenRouterComponent", "LoopComponent", "HumanInTheLoopComponent", "AskHuman",
            "TaskComponent", "RunFlow", "Agent")}
        self.assertEqual(kinds, {
            "ConditionalRouter": "router", "OpenRouterComponent": "component", "LoopComponent": "loop",
            "HumanInTheLoopComponent": "human-input", "AskHuman": "human-input", "TaskComponent": "component",
            "RunFlow": "subflow", "Agent": "agent"})


class FakeWorkflow:
    executors: dict = {}


THE_WORKFLOW = FakeWorkflow()


class ReadsWhetherAFactoryHandsOutOneWorkflow(unittest.TestCase):
    def test_the_same_object_on_both_calls_is_shared(self):
        self.assertIs(_resolve(lambda: THE_WORKFLOW), THE_WORKFLOW)
        self.assertIn(id(THE_WORKFLOW), SHARED)

    def test_a_new_object_on_each_call_is_not(self):
        built = _resolve(lambda: FakeWorkflow())
        self.assertNotIn(id(built), SHARED)


class OutputExecutor:
    workflow_output_types = [str]


class InnerWorkflow:
    def get_output_executors(self):
        return [OutputExecutor()]


class WorkflowExecutor:
    def __init__(self, allow_direct_output):
        self.allow_direct_output = allow_direct_output
        self.workflow = InnerWorkflow()


class ReadsWhatASubWorkflowHostYields(unittest.TestCase):
    def test_by_default_the_inner_outputs_are_sent_on_as_messages(self):
        self.assertEqual(_host_yields(WorkflowExecutor(allow_direct_output=False)), [])

    def test_with_direct_output_it_yields_what_the_inner_output_executors_yield(self):
        self.assertEqual(_host_yields(WorkflowExecutor(allow_direct_output=True)), [str])


if __name__ == "__main__":
    unittest.main()
