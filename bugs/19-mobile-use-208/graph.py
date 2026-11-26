# Derived from mobile-use (github.com/minitap-ai/mobile-use, Apache-2.0) and modified; license text in LICENSE.

import asyncio
import copy
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from enum import Enum
from typing import Annotated, Any, Literal

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, RemoveMessage, ToolCall, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.constants import END, START
from langgraph.graph import StateGraph, add_messages
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import InjectedState, ToolNode
from langgraph.prebuilt.tool_node import ToolRuntime
from langgraph.runtime import Runtime
from langgraph.types import Command
from pydantic import BaseModel

EXECUTOR_MESSAGES_KEY = "executor_messages"
MAX_MESSAGES_IN_HISTORY = 25


class MobileUseContext:
    video_recording_enabled = False
    trace_id = None
    on_agent_thought = None
    on_plan_changes = None


class SubgoalStatus(Enum):
    NOT_STARTED = "NOT_STARTED"
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"


class Subgoal(BaseModel):
    id: Annotated[str, "Unique identifier of the subgoal"]
    description: Annotated[str, "Description of the subgoal"]
    completion_reason: Annotated[
        str | None, "Reason why the subgoal was completed (failure or success)"
    ] = None
    status: SubgoalStatus
    started_at: Annotated[datetime | None, "When the subgoal started"] = None
    ended_at: Annotated[datetime | None, "When the subgoal ended"] = None


def get_current_subgoal(subgoals: list[Subgoal]) -> Subgoal | None:
    return next((s for s in subgoals if s.status == SubgoalStatus.PENDING), None)


def get_subgoals_by_ids(subgoals: list[Subgoal], ids: list[str]) -> list[Subgoal]:
    return [s for s in subgoals if s.id in ids]


def get_next_subgoal(subgoals: list[Subgoal]) -> Subgoal | None:
    return next((s for s in subgoals if s.status == SubgoalStatus.NOT_STARTED), None)


def nothing_started(subgoals: list[Subgoal]) -> bool:
    return all(s.status == SubgoalStatus.NOT_STARTED for s in subgoals)


def complete_subgoals_by_ids(subgoals: list[Subgoal], ids: list[str]) -> list[Subgoal]:
    for subgoal in subgoals:
        if subgoal.id in ids:
            subgoal.status = SubgoalStatus.SUCCESS
            subgoal.ended_at = datetime.now(UTC)
    return subgoals


def fail_current_subgoal(subgoals: list[Subgoal]) -> list[Subgoal]:
    current_subgoal = get_current_subgoal(subgoals)
    if not current_subgoal:
        return subgoals
    current_subgoal.status = SubgoalStatus.FAILURE
    current_subgoal.ended_at = datetime.now(UTC)
    return subgoals


def all_completed(subgoals: list[Subgoal]) -> bool:
    return all(s.status == SubgoalStatus.SUCCESS for s in subgoals)


def one_of_them_is_failure(subgoals: list[Subgoal]) -> bool:
    return any(s.status == SubgoalStatus.FAILURE for s in subgoals)


def start_next_subgoal(subgoals: list[Subgoal]) -> list[Subgoal]:
    next_subgoal = get_next_subgoal(subgoals)
    if not next_subgoal:
        return subgoals
    next_subgoal.status = SubgoalStatus.PENDING
    next_subgoal.started_at = datetime.now(UTC)
    return subgoals


def take_last(a, b):
    return b


class State(BaseModel):
    messages: Annotated[list[AnyMessage], "Sequential messages", add_messages]
    remaining_steps: Annotated[int | None, "Remaining steps before the task is completed"] = None

    initial_goal: Annotated[str, "Initial goal given by the user"]

    subgoal_plan: Annotated[list[Subgoal], "The current plan, made of subgoals"]

    latest_ui_hierarchy: Annotated[
        list[dict] | None, "Latest UI hierarchy of the device", take_last
    ]
    latest_screenshot: Annotated[str | None, "Latest screenshot base64 of the device", take_last]
    focused_app_info: Annotated[str | None, "Focused app info", take_last]
    device_date: Annotated[str | None, "Date of the device", take_last]

    structured_decisions: Annotated[
        str | None,
        "Structured decisions made by the cortex, for the executor to follow",
        take_last,
    ]
    complete_subgoals_by_ids: Annotated[
        list[str],
        "List of subgoal IDs to complete",
        take_last,
    ]

    executor_messages: Annotated[list[AnyMessage], "Sequential Executor messages", add_messages]
    cortex_last_thought: Annotated[str | None, "Last thought of the cortex for the executor"]

    agents_thoughts: Annotated[
        list[str],
        "All thoughts and reasons that led to actions (why a tool was called, expected outcomes..)",
        take_last,
    ]

    scratchpad: Annotated[
        dict[str, str],
        "Persistent key-value storage for notes the agent can save and retrieve",
        take_last,
    ] = {}

    async def asanitize_update(
        self,
        ctx: MobileUseContext,
        update: dict,
        agent: str | None = None,
    ):
        updated_agents_thoughts: str | list[str] | None = update.get("agents_thoughts", None)
        if updated_agents_thoughts is not None:
            if isinstance(updated_agents_thoughts, str):
                updated_agents_thoughts = [updated_agents_thoughts]
            elif isinstance(updated_agents_thoughts, list):
                updated_agents_thoughts = [t for t in updated_agents_thoughts if t is not None]
            else:
                raise ValueError("agents_thoughts must be a str or list[str]")

            if agent is None:
                raise ValueError("Agent is required when updating the 'agents_thoughts' key")
            update["agents_thoughts"] = await _add_agent_thoughts(
                ctx=ctx,
                old=self.agents_thoughts,
                new=updated_agents_thoughts,
                agent=agent,
            )
        return update


async def _add_agent_thoughts(
    ctx: MobileUseContext,
    old: list[str],
    new: list[str],
    agent: str,
) -> list[str]:
    if ctx.on_agent_thought:
        for thought in new:
            await ctx.on_agent_thought(agent, thought)

    named_thoughts = [f"[{agent}] {thought}" for thought in new]
    return old + named_thoughts


class ToolWrapper(BaseModel):
    tool_fn_getter: Callable[[MobileUseContext], BaseTool]
    on_success_fn: Callable[..., str]
    on_failure_fn: Callable[..., str]


def get_save_note_tool(ctx: MobileUseContext) -> BaseTool:
    @tool
    async def save_note(
        agent_thought: str,
        key: str,
        content: str,
        tool_call_id: Annotated[str, InjectedToolCallId],
        state: Annotated[State, InjectedState],
    ):
        """
        Saves a text note to persistent memory with the given key.
        If the key already exists, it will be overwritten.
        """
        updated_scratchpad = {**state.scratchpad, key: content}
        agent_outcome = save_note_wrapper.on_success_fn(key)
        tool_message = ToolMessage(
            tool_call_id=tool_call_id,
            content=agent_outcome,
            status="success",
        )
        return Command(
            update=await state.asanitize_update(
                ctx=ctx,
                update={
                    "agents_thoughts": [agent_thought, agent_outcome],
                    EXECUTOR_MESSAGES_KEY: [tool_message],
                    "scratchpad": updated_scratchpad,
                },
                agent="executor",
            ),
        )

    return save_note


def get_read_note_tool(ctx: MobileUseContext) -> BaseTool:
    @tool
    async def read_note(
        agent_thought: str,
        key: str,
        tool_call_id: Annotated[str, InjectedToolCallId],
        state: Annotated[State, InjectedState],
    ):
        """
        Reads a previously saved note from persistent memory by its key.
        """
        content = state.scratchpad.get(key)
        if content is not None:
            agent_outcome = read_note_wrapper.on_success_fn(key, content)
            status = "success"
        else:
            agent_outcome = read_note_wrapper.on_failure_fn(key)
            status = "error"

        tool_message = ToolMessage(
            tool_call_id=tool_call_id,
            content=agent_outcome,
            status=status,
        )
        return Command(
            update=await state.asanitize_update(
                ctx=ctx,
                update={
                    "agents_thoughts": [agent_thought, agent_outcome],
                    EXECUTOR_MESSAGES_KEY: [tool_message],
                },
                agent="executor",
            ),
        )

    return read_note


def get_list_notes_tool(ctx: MobileUseContext) -> BaseTool:
    @tool
    async def list_notes(
        agent_thought: str,
        tool_call_id: Annotated[str, InjectedToolCallId],
        state: Annotated[State, InjectedState],
    ):
        """
        Lists all note keys currently stored in persistent memory.
        """
        keys = list(state.scratchpad.keys())
        agent_outcome = list_notes_wrapper.on_success_fn(keys)
        tool_message = ToolMessage(
            tool_call_id=tool_call_id,
            content=agent_outcome,
            status="success",
        )
        return Command(
            update=await state.asanitize_update(
                ctx=ctx,
                update={
                    "agents_thoughts": [agent_thought, agent_outcome],
                    EXECUTOR_MESSAGES_KEY: [tool_message],
                },
                agent="executor",
            ),
        )

    return list_notes


save_note_wrapper = ToolWrapper(
    tool_fn_getter=get_save_note_tool,
    on_success_fn=lambda key: f"Successfully saved note '{key}'.",
    on_failure_fn=lambda key: f"Failed to save note '{key}'.",
)

read_note_wrapper = ToolWrapper(
    tool_fn_getter=get_read_note_tool,
    on_success_fn=lambda key, content: (
        f"Successfully read note '{key}'. '{key}' note full content: {content}"
    ),
    on_failure_fn=lambda key: f"Note '{key}' not found in scratchpad.",
)

list_notes_wrapper = ToolWrapper(
    tool_fn_getter=get_list_notes_tool,
    on_success_fn=lambda keys: (
        f"Here are all the note keys: {keys}" if keys else "No notes saved yet."
    ),
    on_failure_fn=lambda: "Failed to list notes.",
)

EXECUTOR_WRAPPERS_TOOLS = [
    save_note_wrapper,
    read_note_wrapper,
    list_notes_wrapper,
]

VIDEO_RECORDING_WRAPPERS: list[ToolWrapper] = []


def get_tools_from_wrappers(
    ctx: MobileUseContext,
    wrappers: list[ToolWrapper],
) -> list[BaseTool]:
    tools: list[BaseTool] = []
    for wrapper in wrappers:
        tools.append(wrapper.tool_fn_getter(ctx))
    return tools


class PlannerNode:
    def __init__(self, ctx: MobileUseContext):
        self.ctx = ctx

    async def __call__(self, state: State):
        subgoals_plan = [
            Subgoal(
                id="s1",
                description="",
                status=SubgoalStatus.NOT_STARTED,
                completion_reason=None,
            )
        ]
        return await state.asanitize_update(
            ctx=self.ctx,
            update={
                "subgoal_plan": subgoals_plan,
            },
            agent="planner",
        )


class OrchestratorNode:
    def __init__(self, ctx: MobileUseContext):
        self.ctx = ctx

    async def __call__(self, state: State):
        no_subgoal_started = nothing_started(state.subgoal_plan)
        current_subgoal = get_current_subgoal(state.subgoal_plan)

        if no_subgoal_started or not current_subgoal:
            state.subgoal_plan = start_next_subgoal(state.subgoal_plan)
            new_subgoal = get_current_subgoal(state.subgoal_plan)
            thoughts = [
                (
                    f"Starting the first subgoal: {new_subgoal}"
                    if no_subgoal_started
                    else f"Starting the next subgoal: {new_subgoal}"
                )
            ]
            return await _get_state_update(
                ctx=self.ctx, state=state, thoughts=thoughts, update_plan=True
            )

        subgoals_to_examine = get_subgoals_by_ids(
            subgoals=state.subgoal_plan,
            ids=state.complete_subgoals_by_ids,
        )
        if len(subgoals_to_examine) <= 0:
            return await _get_state_update(
                ctx=self.ctx, state=state, thoughts=["No subgoal to examine."]
            )

        needs_replaning = False
        completed_subgoal_ids = [s.id for s in subgoals_to_examine]
        reason = ""
        if needs_replaning:
            thoughts = [reason]
            state.subgoal_plan = fail_current_subgoal(state.subgoal_plan)
            thoughts.append("==== END OF PLAN, REPLANNING ====")
            return await _get_state_update(
                ctx=self.ctx, state=state, thoughts=thoughts, update_plan=True
            )

        state.subgoal_plan = complete_subgoals_by_ids(
            subgoals=state.subgoal_plan,
            ids=completed_subgoal_ids,
        )
        thoughts = [reason]
        if all_completed(state.subgoal_plan):
            return await _get_state_update(
                ctx=self.ctx, state=state, thoughts=thoughts, update_plan=True
            )

        if current_subgoal.id not in completed_subgoal_ids:
            return await _get_state_update(
                ctx=self.ctx, state=state, thoughts=thoughts, update_plan=True
            )

        state.subgoal_plan = start_next_subgoal(state.subgoal_plan)
        new_subgoal = get_current_subgoal(state.subgoal_plan)
        thoughts.append(f"==== NEXT SUBGOAL: {new_subgoal} ====")
        return await _get_state_update(
            ctx=self.ctx, state=state, thoughts=thoughts, update_plan=True
        )


async def _get_state_update(
    ctx: MobileUseContext,
    state: State,
    thoughts: list[str],
    update_plan: bool = False,
):
    update = {
        "agents_thoughts": thoughts,
        "complete_subgoals_by_ids": [],
    }
    if update_plan:
        update["subgoal_plan"] = state.subgoal_plan
        if ctx.on_plan_changes:
            await ctx.on_plan_changes(state.subgoal_plan, False)
    return await state.asanitize_update(ctx=ctx, update=update, agent="orchestrator")


class ContextorNode:
    def __init__(self, ctx: MobileUseContext):
        self.ctx = ctx

    async def __call__(self, state: State):
        agent_outcome: str | None = None
        return await state.asanitize_update(
            ctx=self.ctx,
            update={
                "latest_ui_hierarchy": [],
                "latest_screenshot": "",
                "focused_app_info": None,
                "screen_size": (0, 0),
                "device_date": None,
                "agents_thoughts": [agent_outcome],
            },
            agent="contextor",
        )


class CortexNode:
    def __init__(self, ctx: MobileUseContext):
        self.ctx = ctx

    async def __call__(self, state: State):
        decisions = None
        complete_ids: list[str] = []
        agent_thought = ""
        return await state.asanitize_update(
            ctx=self.ctx,
            update={
                "agents_thoughts": [agent_thought],
                "structured_decisions": decisions,
                "complete_subgoals_by_ids": complete_ids,
                "latest_ui_hierarchy": None,
                "latest_screenshot": None,
                "focused_app_info": None,
                "device_date": None,
                EXECUTOR_MESSAGES_KEY: [RemoveMessage(id=REMOVE_ALL_MESSAGES)],
                "cortex_last_thought": agent_thought,
            },
            agent="cortex",
        )


class ExecutorNode:
    def __init__(self, ctx: MobileUseContext):
        self.ctx = ctx

    async def __call__(self, state: State):
        structured_decisions = state.structured_decisions
        if not structured_decisions:
            return await state.asanitize_update(
                ctx=self.ctx,
                update={
                    "agents_thoughts": [
                        "No structured decisions found, I cannot execute anything."
                    ],
                },
                agent="executor",
            )

        cortex_last_thought = (
            state.cortex_last_thought if state.cortex_last_thought else state.agents_thoughts[-1]
        )
        response = AIMessage(content="")
        return await state.asanitize_update(
            ctx=self.ctx,
            update={
                "cortex_last_thought": cortex_last_thought,
                EXECUTOR_MESSAGES_KEY: [response],
            },
            agent="executor",
        )


class ExecutorToolNode(ToolNode):
    """
    ToolNode that runs tool calls one after the other - not simultaneously.
    If one error occurs, the remaining tool calls are aborted!
    """

    def __init__(self, tools, messages_key: str, trace_id: str | None = None):
        super().__init__(tools=tools, messages_key=messages_key)
        self._trace_id = trace_id

    async def _afunc(self, input, config: RunnableConfig, runtime: Runtime):
        return await self.__func(is_async=True, input=input, config=config, runtime=runtime)

    def _func(self, input, config: RunnableConfig, runtime: Runtime) -> Any:
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(
            self.__func(is_async=False, input=input, config=config, runtime=runtime)
        )

    def _build_tool_runtime(self, call: ToolCall, input, config: RunnableConfig, runtime: Runtime) -> Any:
        state = self._extract_state(input)
        return ToolRuntime(
            state=state,
            tool_call_id=call["id"],
            config=config,
            context=runtime.context,
            store=runtime.store,
            stream_writer=runtime.stream_writer,
        )

    async def __func(self, is_async: bool, input, config: RunnableConfig, runtime: Runtime) -> Any:
        tool_calls, input_type = self._parse_input(input)
        outputs: list[Command | ToolMessage] = []
        failed = False
        for call in tool_calls:
            tool_runtime = self._build_tool_runtime(call, input, config, runtime)
            if failed:
                output = self._get_erroneous_command(
                    call=call,
                    message="Aborted: a previous tool call failed!",
                )
            else:
                if is_async:
                    output = await self._arun_one(call, input_type, tool_runtime)
                else:
                    output = self._run_one(call, input_type, tool_runtime)
                failed = self._has_tool_call_failed(call, output)
                if failed is None:
                    output = self._get_erroneous_command(
                        call=call,
                        message=f"Unexpected tool output type: {type(output)}",
                    )
                    failed = True
            outputs.append(output)
        return self._combine_tool_outputs(outputs, input_type)  # type: ignore

    def _has_tool_call_failed(self, call: ToolCall, output: ToolMessage | Command) -> bool | None:
        if isinstance(output, ToolMessage):
            return output.status == "error"
        if isinstance(output, Command):
            output_msg = self._get_tool_message(output)
            return output_msg.status == "error"
        return None

    def _get_erroneous_command(self, call: ToolCall, message: str) -> Command:
        tool_message = ToolMessage(
            name=call["name"], tool_call_id=call["id"], content=message, status="error"
        )
        return Command(update={self._messages_key: [tool_message]})

    def _get_tool_message(self, cmd: Command) -> ToolMessage:
        msg = cmd.update.get(self._messages_key)
        return msg[-1] if isinstance(msg, list) else msg


class SummarizerNode:
    def __init__(self, ctx: MobileUseContext):
        self.ctx = ctx

    async def __call__(self, state: State):
        if len(state.messages) <= MAX_MESSAGES_IN_HISTORY:
            return {}

        nb_removal_candidates = len(state.messages) - MAX_MESSAGES_IN_HISTORY

        remove_messages = []
        start_removal = False

        for msg in reversed(state.messages[:nb_removal_candidates]):
            if isinstance(msg, ToolMessage | HumanMessage):
                start_removal = True
            if start_removal and msg.id:
                remove_messages.append(RemoveMessage(id=msg.id))
            return await state.asanitize_update(
                ctx=self.ctx,
                update={
                    "messages": remove_messages,
                },
            )


def convergence_node(state: State):
    """Convergence point for parallel execution paths."""
    return {}


def convergence_gate(
    state: State,
) -> Literal["continue", "replan", "end"]:
    """Check if all subgoals are completed at convergence point."""
    if one_of_them_is_failure(state.subgoal_plan):
        return "replan"

    if all_completed(state.subgoal_plan):
        return "end"

    if not get_current_subgoal(state.subgoal_plan):
        return "end"

    return "continue"


def post_cortex_gate(
    state: State,
) -> Sequence[str]:
    node_sequence = []

    if len(state.complete_subgoals_by_ids) > 0 or not state.structured_decisions:
        node_sequence.append("review_subgoals")

    if state.structured_decisions:
        node_sequence.append("execute_decisions")

    return node_sequence


def post_executor_gate(
    state: State,
) -> Literal["invoke_tools", "skip"]:
    messages = state.executor_messages
    if not messages:
        return "skip"
    last_message = messages[-1]

    if isinstance(last_message, AIMessage):
        tool_calls = getattr(last_message, "tool_calls", None)
        if tool_calls and len(tool_calls) > 0:
            return "invoke_tools"
    return "skip"


async def get_graph(ctx: MobileUseContext) -> CompiledStateGraph:
    graph_builder = StateGraph(State)

    graph_builder.add_node("planner", PlannerNode(ctx))
    graph_builder.add_node("orchestrator", OrchestratorNode(ctx))

    graph_builder.add_node("contextor", ContextorNode(ctx))

    graph_builder.add_node("cortex", CortexNode(ctx))

    graph_builder.add_node("executor", ExecutorNode(ctx))

    executor_wrappers = list(EXECUTOR_WRAPPERS_TOOLS)
    if ctx.video_recording_enabled:
        executor_wrappers.extend(VIDEO_RECORDING_WRAPPERS)

    executor_tool_node = ExecutorToolNode(
        tools=get_tools_from_wrappers(ctx=ctx, wrappers=executor_wrappers),
        messages_key=EXECUTOR_MESSAGES_KEY,
        trace_id=ctx.trace_id,
    )
    graph_builder.add_node("executor_tools", executor_tool_node)

    graph_builder.add_node("summarizer", SummarizerNode(ctx))

    graph_builder.add_node(node="convergence", action=convergence_node, defer=True)

    graph_builder.add_edge(START, "planner")
    graph_builder.add_edge("planner", "orchestrator")
    graph_builder.add_edge("orchestrator", "convergence")
    graph_builder.add_edge("contextor", "cortex")
    graph_builder.add_conditional_edges(
        "cortex",
        post_cortex_gate,
        {
            "review_subgoals": "orchestrator",
            "execute_decisions": "executor",
        },
    )
    graph_builder.add_conditional_edges(
        "executor",
        post_executor_gate,
        {"invoke_tools": "executor_tools", "skip": "summarizer"},
    )
    graph_builder.add_edge("executor_tools", "summarizer")

    graph_builder.add_edge("summarizer", "convergence")

    graph_builder.add_conditional_edges(
        source="convergence",
        path=convergence_gate,
        path_map={
            "continue": "contextor",
            "replan": "planner",
            "end": END,
        },
    )

    return graph_builder.compile()


graph = asyncio.run(get_graph(MobileUseContext()))
