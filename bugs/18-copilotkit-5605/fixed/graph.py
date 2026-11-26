# Derived from CopilotKit (github.com/CopilotKit/CopilotKit, MIT) and modified; license text in LICENSE.

import uuid
from typing import Any, Dict, List

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.types import Command
from typing_extensions import TypedDict


class CopilotKitProperties(TypedDict):
    actions: List[Any]
    context: List[Any]
    intercepted_tool_calls: Any
    original_ai_message_id: Any


class CopilotKitState(MessagesState):
    copilotkit: CopilotKitProperties


async def copilotkit_emit_state(config: RunnableConfig, state: Any) -> None:
    return None


class StackAgentState(CopilotKitState):
    tool_logs: List[Dict[str, Any]]
    analysis: Dict[str, Any]
    show_cards: bool
    context: Dict[str, Any]
    last_user_content: str


async def gather_context_node(state: StackAgentState, config: RunnableConfig):
    last_user_content = state["messages"][-1].content if state["messages"] else ""
    parsed = None

    if not parsed:
        return Command(
            goto="analyze",
            update={
                "analysis": state["analysis"],
                "context": {},
                "tool_logs": state["tool_logs"],
                "show_cards": False,
                "last_user_content": last_user_content,
            },
        )

    state["tool_logs"] = state.get("tool_logs", [])
    state["tool_logs"].append(
        {"id": str(uuid.uuid4()), "message": "Extracting GitHub URL", "status": "processing"}
    )
    context: Dict[str, Any] = {}
    state["tool_logs"][-1]["status"] = "completed"
    await copilotkit_emit_state(config, state)

    return Command(
        goto="analyze",
        update={
            "analysis": state["analysis"],
            "context": context,
            "tool_logs": state["tool_logs"],
            "show_cards": False,
            "last_user_content": last_user_content,
        },
    )


async def analyze_with_gemini_node(state: StackAgentState, config: RunnableConfig):
    context = state.get("context", {})
    if not context:
        state["messages"].append(AIMessage(content="Please provide a valid GitHub URL"))
        return Command(
            goto="end",
            update={
                "messages": state["messages"],
                "show_cards": state["show_cards"],
                "analysis": state["analysis"],
            },
        )

    state["tool_logs"] = state.get("tool_logs", [])
    state["tool_logs"].append(
        {"id": str(uuid.uuid4()), "message": "Analyzing stack", "status": "processing"}
    )
    await copilotkit_emit_state(config, state)
    state["tool_logs"][-1]["status"] = "completed"
    await copilotkit_emit_state(config, state)
    state["messages"].append(AIMessage(content=""))
    return Command(
        goto="end",
        update={
            "messages": state["messages"],
            "show_cards": True,
            "analysis": state["analysis"],
        },
    )


async def end_node(state: StackAgentState, config: RunnableConfig):
    state["tool_logs"] = []
    await copilotkit_emit_state(config or RunnableConfig(recursion_limit=25), state)
    return Command(
        goto=END,
        update={
            "messages": state["messages"],
            "show_cards": state["show_cards"],
            "analysis": state["analysis"],
        },
    )


workflow = StateGraph(StackAgentState)
workflow.add_node("gather_context", gather_context_node)
workflow.add_node("analyze", analyze_with_gemini_node)
workflow.add_node("end", end_node)
workflow.add_edge(START, "gather_context")
workflow.add_edge("gather_context", "analyze")
workflow.add_edge("analyze", "end")
workflow.set_entry_point("gather_context")
workflow.set_finish_point("end")

stack_analysis_graph = workflow.compile(checkpointer=MemorySaver())
