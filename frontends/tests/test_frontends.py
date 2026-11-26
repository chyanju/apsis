"""Tests of the front-ends that need no framework installed: python3 -m unittest discover -s frontends/tests"""
import functools
import json
import os
import sys
import tempfile
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
for package in ("common", "langflow", "flowise", "langgraph", "agent-framework", "autogen"):
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
from apsis_langgraph.astutil import (  # noqa: E402
    _ast_command_send_targets,
    _node_func,
    _node_source_ast,
    _router_return_targets,
)


def written(obj) -> str:
    """Write `obj` as JSON to a temporary file and return its path."""
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(obj, f)
    f.close()
    return f.name


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
