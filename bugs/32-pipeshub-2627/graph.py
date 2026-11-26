# Derived from PipesHub (github.com/pipeshub-ai/pipeshub-ai, Apache-2.0) and modified; license text in LICENSE.
"""The deep agent of PipesHub: orchestrator, critic, sub-agents, aggregator and respond, with the retry and continue
loop from the aggregator back to the orchestrator. The node bodies keep the state they read and write; planning,
critique and evaluation by the model are replaced by constants."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph
from langgraph.types import StreamWriter
from typing_extensions import TypedDict

# app/modules/agents/deep/state.py


class SubAgentTask(TypedDict, total=False):
    task_id: str
    description: str
    depends_on: list[str]
    status: str  # "pending" | "running" | "success" | "error" | "skipped"
    result: dict[str, Any] | None
    error: str | None


class DeepAgentState(TypedDict, total=False):
    query: str
    error: dict[str, Any] | None
    response: str | None
    reflection_decision: str
    reflection: dict[str, Any]
    task_plan: dict[str, Any] | None
    execution_plan: dict[str, Any] | None
    sub_agent_tasks: list[SubAgentTask]
    completed_tasks: list[SubAgentTask]
    evaluation: dict[str, Any] | None
    deep_iteration_count: int
    deep_max_iterations: int
    critic_approved: bool | None
    critic_feedback: str
    critic_done: bool


# app/modules/agents/deep/orchestrator.py


async def orchestrator_node(state: DeepAgentState, config: RunnableConfig, writer: StreamWriter) -> DeepAgentState:
    """Decompose the query into sub-tasks; on a later pass, plan again from the evaluation."""
    query = state.get("query", "")
    critic_feedback = state.get("critic_feedback", "")
    if critic_feedback:
        state["critic_feedback"] = ""  # consume — don't re-inject next time
    # the model's plan; its task ids are plain strings such as `task_1`, on every pass
    plan = {"tasks": [{"task_id": "task_1", "description": query, "depends_on": []},
                      {"task_id": "task_2", "description": "summarize task_1", "depends_on": ["task_1"]}]}
    state["task_plan"] = plan
    state["sub_agent_tasks"] = plan["tasks"]
    state["execution_plan"] = {"can_answer_directly": False}
    return state


def should_dispatch(state: DeepAgentState) -> Literal["dispatch", "respond"]:
    if state.get("error"):
        return "respond"
    plan = state.get("execution_plan", {})
    if plan.get("can_answer_directly"):
        return "respond"
    tasks = state.get("sub_agent_tasks", [])
    if not tasks:
        return "respond"
    return "dispatch"


# app/modules/agents/deep/orchestrator_critic.py


async def critic_node(state: DeepAgentState, config: RunnableConfig, writer: StreamWriter) -> DeepAgentState:
    """Evaluate the plan once per request."""
    state["critic_approved"] = True
    state["critic_feedback"] = ""
    state["critic_done"] = True
    return state


def route_after_critic(state: DeepAgentState) -> Literal["dispatch", "orchestrator", "respond"]:
    if state.get("error"):
        return "respond"
    if state.get("critic_approved"):
        execution_plan = state.get("execution_plan", {}) or {}
        if execution_plan.get("can_answer_directly"):
            return "respond"
        tasks = state.get("sub_agent_tasks", []) or []
        return "dispatch" if tasks else "respond"
    return "orchestrator"


# app/modules/agents/deep/sub_agent.py


async def _execute_single_sub_agent(task: SubAgentTask, state: DeepAgentState, completed_tasks: list[SubAgentTask],
                                    config: RunnableConfig, writer: StreamWriter) -> SubAgentTask:
    # the results of the tasks it depends on, looked up by task id
    dependency_results = [
        t.get("result") for t in completed_tasks
        if t.get("task_id") in (task.get("depends_on") or []) and t.get("status") == "success"
    ]
    return {**task, "status": "success", "result": {"response": f"{task['task_id']} from {len(dependency_results)} results"}}


async def execute_sub_agents_node(state: DeepAgentState, config: RunnableConfig, writer: StreamWriter) -> DeepAgentState:
    """Execute all sub-agent tasks respecting dependencies."""
    tasks = state.get("sub_agent_tasks", [])

    if not tasks:
        return state

    completed: list[SubAgentTask] = list(state.get("completed_tasks", []))

    task_events: dict[str, asyncio.Event] = {}

    # Already-completed tasks (from prior aggregator iterations) are done
    for t in completed:
        tid = t.get("task_id", "")
        if tid:
            evt = asyncio.Event()
            evt.set()
            task_events[tid] = evt

    # Create events for new tasks
    for t in tasks:
        task_events[t["task_id"]] = asyncio.Event()

    async def _run_when_ready(task: SubAgentTask) -> None:
        task_id = task.get("task_id", "unknown")
        try:
            dep_ids = task.get("depends_on", [])
            if dep_ids:
                await asyncio.gather(*[task_events[d].wait() for d in dep_ids if d in task_events])
            result = await _execute_single_sub_agent(task, state, completed, config, writer)
            completed.append(result)
        except Exception as exc:
            completed.append({**task, "status": "error", "error": str(exc)})
        finally:
            task_events[task_id].set()

    await asyncio.gather(*[_run_when_ready(t) for t in tasks])

    state["completed_tasks"] = completed
    return state


# app/modules/agents/deep/aggregator.py


async def aggregator_node(state: DeepAgentState, config: RunnableConfig, writer: StreamWriter) -> DeepAgentState:
    """Evaluate the results and decide whether to respond, retry or continue."""
    completed = state.get("completed_tasks", [])
    iteration = state.get("deep_iteration_count", 0)
    max_iter = state.get("deep_max_iterations", 3)
    errors = [t for t in completed if t.get("status") == "error"]
    # the model's evaluation
    evaluation = {"decision": "continue" if iteration + 1 < max_iter else "respond_success", "errors": len(errors)}
    state["evaluation"] = evaluation
    if evaluation["decision"] == "continue":
        state["reflection_decision"] = "continue"
        state["reflection"] = {"reason": "more information is needed"}
        state["deep_iteration_count"] = state.get("deep_iteration_count", 0) + 1
        state["sub_agent_tasks"] = []
    else:
        state["reflection_decision"] = "respond_success"
        state["reflection"] = {"reason": "results are complete"}
    return state


def route_after_evaluation(state: DeepAgentState) -> Literal["respond", "retry", "continue"]:
    """Route based on aggregator's evaluation decision."""
    decision = state.get("reflection_decision", "respond_success")
    if decision in ("respond_success", "respond_error", "respond_clarify"):
        return "respond"
    if decision == "retry":
        return "retry"
    if decision == "continue":
        return "continue"
    return "respond"


# app/modules/agents/deep/respond.py


async def deep_respond_node(state: DeepAgentState, config: RunnableConfig, writer: StreamWriter) -> DeepAgentState:
    completed = state.get("completed_tasks", [])
    state["response"] = "\n".join(str((t.get("result") or {}).get("response")) for t in completed if t.get("status") == "success")
    return state


# app/modules/agents/deep/graph.py


def route_after_orchestrator(state: DeepAgentState) -> Literal["critic", "dispatch", "respond"]:
    """First run (critic_done=False): always go to critic; later runs bypass it."""
    if state.get("error"):
        return "respond"

    if not state.get("critic_done", False):
        execution_plan = state.get("execution_plan", {}) or {}
        if execution_plan.get("can_answer_directly"):
            return "respond"
        return "critic"

    return should_dispatch(state)  # "dispatch" or "respond"


def create_deep_agent_graph():
    workflow = StateGraph(DeepAgentState)

    workflow.add_node("orchestrator", orchestrator_node)
    workflow.add_node("critic", critic_node)
    workflow.add_node("execute_sub_agents", execute_sub_agents_node)
    workflow.add_node("aggregator", aggregator_node)
    workflow.add_node("respond", deep_respond_node)

    workflow.set_entry_point("orchestrator")

    workflow.add_conditional_edges(
        "orchestrator",
        route_after_orchestrator,
        {
            "critic": "critic",
            "dispatch": "execute_sub_agents",
            "respond": "respond",
        },
    )

    workflow.add_conditional_edges(
        "critic",
        route_after_critic,
        {
            "dispatch": "execute_sub_agents",
            "orchestrator": "orchestrator",
            "respond": "respond",
        },
    )

    workflow.add_edge("execute_sub_agents", "aggregator")

    workflow.add_conditional_edges(
        "aggregator",
        route_after_evaluation,
        {
            "respond": "respond",
            "retry": "orchestrator",
            "continue": "orchestrator",
        },
    )

    workflow.add_edge("respond", END)

    return workflow.compile()


deep_agent_graph = create_deep_agent_graph()
