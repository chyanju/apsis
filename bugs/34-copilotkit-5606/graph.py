# Derived from CopilotKit (github.com/CopilotKit/CopilotKit, MIT) and modified; license text in LICENSE.

from typing import Any, Dict, List, Optional

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.graph import END, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import Command
from typing_extensions import Literal, TypedDict


class CopilotContextItem(TypedDict):
    description: str
    value: Any


class CopilotKitProperties(TypedDict):
    actions: List[Any]
    context: List[CopilotContextItem]
    intercepted_tool_calls: Any
    original_ai_message_id: Any


class CopilotKitState(MessagesState):
    copilotkit: CopilotKitProperties


class AgentState(CopilotKitState):
    proverbs: List[str] = []
    tools: List[Any] = []
    items: List[Dict[str, Any]] = []
    globalTitle: str = ""
    globalDescription: str = ""
    planSteps: List[Dict[str, Any]] = []
    currentStepIndex: int = -1
    planStatus: str = ""


@tool
def set_plan(steps: List[str]):
    """
    Initialize a plan consisting of step descriptions. Resets progress and sets status to 'in_progress'.
    """
    return {"initialized": True, "steps": steps}


@tool
def update_plan_progress(
    step_index: int,
    status: Literal["pending", "in_progress", "completed", "blocked", "failed"],
    note: Optional[str] = None,
):
    """
    Update a single plan step's status, and optionally add a note.
    """
    return {"updated": True, "index": step_index, "status": status, "note": note}


@tool
def complete_plan():
    """
    Mark the plan as completed.
    """
    return {"completed": True}


backend_tools = [
    set_plan,
    update_plan_progress,
    complete_plan,
]

backend_tool_names = [tool.name for tool in backend_tools]


async def chat_node(
    state: AgentState, config: RunnableConfig
) -> Command[Literal["tool_node", "__end__"]]:
    plan_steps = state.get("planSteps", []) or []
    current_step_index = state.get("currentStepIndex", -1)
    plan_status = state.get("planStatus", "")

    full_messages = state.get("messages", []) or []
    try:
        if full_messages:
            last_msg = full_messages[-1]
            if isinstance(last_msg, AIMessage):
                pending_frontend_call = False
                for tc in getattr(last_msg, "tool_calls", []) or []:
                    name = (
                        tc.get("name")
                        if isinstance(tc, dict)
                        else getattr(tc, "name", None)
                    )
                    if name and name not in backend_tool_names:
                        pending_frontend_call = True
                        break
                if pending_frontend_call:
                    return Command(
                        goto=END,
                        update={
                            "items": state.get("items", []),
                            "globalTitle": state.get("globalTitle", ""),
                            "globalDescription": state.get("globalDescription", ""),
                            "itemsCreated": state.get("itemsCreated", 0),
                            "lastAction": state.get("lastAction", ""),
                            "planSteps": state.get("planSteps", []),
                            "currentStepIndex": state.get("currentStepIndex", -1),
                            "planStatus": state.get("planStatus", ""),
                        },
                    )
    except Exception:
        pass

    response = AIMessage(content="")

    try:
        tool_calls = getattr(response, "tool_calls", []) or []
        predicted_plan_steps = plan_steps.copy()
        predicted_current_index = current_step_index
        predicted_plan_status = plan_status
        for tc in tool_calls:
            name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
            args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", {})
            if name == "set_plan":
                raw_steps = args.get("steps") or []
                predicted_plan_steps = [
                    {"title": s if isinstance(s, str) else str(s), "status": "pending"}
                    for s in raw_steps
                ]
                if predicted_plan_steps:
                    predicted_plan_steps[0]["status"] = "in_progress"
                    predicted_current_index = 0
                    predicted_plan_status = "in_progress"
                else:
                    predicted_current_index = -1
                    predicted_plan_status = ""
            elif name == "update_plan_progress":
                idx = args.get("step_index")
                status = args.get("status")
                if (
                    isinstance(idx, int)
                    and 0 <= idx < len(predicted_plan_steps)
                    and isinstance(status, str)
                ):
                    predicted_plan_steps[idx]["status"] = status
                    if status == "in_progress":
                        predicted_current_index = idx
                        predicted_plan_status = "in_progress"
                    if status == "completed" and idx >= predicted_current_index:
                        predicted_current_index = idx
            elif name == "complete_plan":
                for i in range(len(predicted_plan_steps)):
                    if predicted_plan_steps[i].get("status") != "completed":
                        predicted_plan_steps[i]["status"] = "completed"
                predicted_plan_status = "completed"
        plan_updates = {}
        if predicted_plan_steps != plan_steps:
            plan_updates["planSteps"] = predicted_plan_steps
        if predicted_current_index != current_step_index:
            plan_updates["currentStepIndex"] = predicted_current_index
        if predicted_plan_status != plan_status:
            plan_updates["planStatus"] = predicted_plan_status
    except Exception:
        plan_updates = {}

    if route_to_tool_node(response):
        return Command(
            goto="tool_node",
            update={
                "messages": [response],
                "items": state.get("items", []),
                "globalTitle": state.get("globalTitle", ""),
                "globalDescription": state.get("globalDescription", ""),
                "itemsCreated": state.get("itemsCreated", 0),
                "lastAction": state.get("lastAction", ""),
                "planSteps": state.get("planSteps", []),
                "currentStepIndex": state.get("currentStepIndex", -1),
                "planStatus": state.get("planStatus", ""),
                **plan_updates,
                "__last_tool_guidance": "If a deletion tool reports success (deleted:ID), acknowledge deletion even if the item no longer exists afterwards.",
            },
        )

    try:
        effective_steps = plan_updates.get("planSteps", plan_steps)
        effective_plan_status = plan_updates.get("planStatus", plan_status)
        has_remaining = bool(effective_steps) and any(
            (s.get("status") not in ("completed", "failed")) for s in effective_steps
        )
    except Exception:
        effective_steps = plan_steps
        effective_plan_status = plan_status
        has_remaining = False

    try:
        tool_calls = getattr(response, "tool_calls", []) or []
    except Exception:
        tool_calls = []
    has_frontend_tool_calls = False
    for tc in tool_calls:
        name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
        if name and name not in backend_tool_names:
            has_frontend_tool_calls = True
            break

    if has_frontend_tool_calls:
        return Command(
            goto=END,
            update={
                "messages": [response],
                "items": state.get("items", []),
                "globalTitle": state.get("globalTitle", ""),
                "globalDescription": state.get("globalDescription", ""),
                "itemsCreated": state.get("itemsCreated", 0),
                "lastAction": state.get("lastAction", ""),
                "planSteps": state.get("planSteps", []),
                "currentStepIndex": state.get("currentStepIndex", -1),
                "planStatus": state.get("planStatus", ""),
                **plan_updates,
                "__last_tool_guidance": (
                    "Frontend tool calls issued. Waiting for client tool results before continuing."
                ),
            },
        )

    if has_remaining and effective_plan_status != "completed":
        return Command(
            goto="chat_node",
            update={
                "messages": ([]),
                "items": state.get("items", []),
                "globalTitle": state.get("globalTitle", ""),
                "globalDescription": state.get("globalDescription", ""),
                "itemsCreated": state.get("itemsCreated", 0),
                "lastAction": state.get("lastAction", ""),
                "planSteps": state.get("planSteps", []),
                "currentStepIndex": state.get("currentStepIndex", -1),
                "planStatus": state.get("planStatus", ""),
                **plan_updates,
                "__last_tool_guidance": (
                    "Plan is in progress. Proceed to the next step automatically. "
                    "Update the step status to in_progress, call necessary tools, and mark it completed when done."
                ),
            },
        )

    try:
        all_steps_completed = bool(effective_steps) and all(
            (s.get("status") == "completed") for s in effective_steps
        )
        plan_marked_completed = effective_plan_status == "completed"
    except Exception:
        all_steps_completed = False
        plan_marked_completed = False

    if all_steps_completed and not plan_marked_completed:
        return Command(
            goto="chat_node",
            update={
                "messages": [response] if has_frontend_tool_calls else ([]),
                "items": state.get("items", []),
                "globalTitle": state.get("globalTitle", ""),
                "globalDescription": state.get("globalDescription", ""),
                "itemsCreated": state.get("itemsCreated", 0),
                "lastAction": state.get("lastAction", ""),
                "planSteps": state.get("planSteps", []),
                "currentStepIndex": state.get("currentStepIndex", -1),
                "planStatus": state.get("planStatus", ""),
                **plan_updates,
                "__last_tool_guidance": (
                    "All steps are completed. Call complete_plan to mark the plan as finished, "
                    "then present a concise summary of outcomes."
                ),
            },
        )

    currently_in_progress = plan_updates.get("planStatus", plan_status) == "in_progress"
    final_messages = (
        [response] if (has_frontend_tool_calls or not currently_in_progress) else ([])
    )
    return Command(
        goto=END,
        update={
            "messages": final_messages,
            "items": state.get("items", []),
            "globalTitle": state.get("globalTitle", ""),
            "globalDescription": state.get("globalDescription", ""),
            "itemsCreated": state.get("itemsCreated", 0),
            "lastAction": state.get("lastAction", ""),
            "planSteps": state.get("planSteps", []),
            "currentStepIndex": state.get("currentStepIndex", -1),
            "planStatus": state.get("planStatus", ""),
            **plan_updates,
            "__last_tool_guidance": None,
        },
    )


def route_to_tool_node(response: BaseMessage):
    tool_calls = getattr(response, "tool_calls", None)
    if not tool_calls:
        return False

    for tool_call in tool_calls:
        name = tool_call.get("name")
        if name in backend_tool_names:
            return True
    return False


workflow = StateGraph(AgentState)
workflow.add_node("chat_node", chat_node)
workflow.add_node("tool_node", ToolNode(tools=backend_tools))
workflow.add_edge("tool_node", "chat_node")
workflow.set_entry_point("chat_node")

graph = workflow.compile()
