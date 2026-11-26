# Derived from DATAGEN (github.com/starpig1129/DATAGEN, MIT) and modified; license text in LICENSE.

from __future__ import annotations

from typing import Annotated, Any, Literal, cast

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel, ConfigDict, Field


class State(BaseModel):
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        validate_assignment=True,
        extra='ignore'
    )

    messages: list[BaseMessage] = Field(
        default_factory=list,
        description="Sequence of messages exchanged in the workflow"
    )
    last_active_agent: str | None = Field(
        default=None,
        description="The last agent that performed an action"
    )
    step_count: int = Field(
        default=0,
        description="Safety counter to prevent infinite loops"
    )
    current_instruction: str | None = Field(
        default=None,
        description="Specific task assigned to the next agent"
    )
    next_workflow_step: str | None = Field(
        default=None,
        description="The next node/agent to route to"
    )
    todo_list: list[str] = Field(
        default_factory=list,
        description="List of pending subtasks"
    )
    completed_tasks: list[str] = Field(
        default_factory=list,
        description="List of completed subtasks"
    )
    hypothesis: str | None = Field(
        default=None,
        description="Current research hypothesis"
    )
    search_artifacts: dict[str, str] = Field(
        default_factory=dict,
        description="Map of {path: summary} for search results"
    )
    data_viz_artifacts: dict[str, str] = Field(
        default_factory=dict,
        description="Map of {path: summary} for visualizations"
    )
    code_artifacts: dict[str, str] = Field(
        default_factory=dict,
        description="Map of {path: summary} for code files"
    )
    report_artifacts: dict[str, str] = Field(
        default_factory=dict,
        description="Map of {section: path/content} for report sections"
    )
    quality_feedback: str | None = Field(
        default=None,
        description="Feedback from quality review"
    )
    needs_revision: bool = Field(
        default=False,
        description="Flag to trigger revision loop"
    )
    revision_count: int = Field(
        default=0,
        description="Counter for consecutive revision attempts"
    )


NodeType = Literal['Visualization', 'Search', 'Coder', 'Report', 'Process', 'NoteTaker', 'Hypothesis', 'QualityReview']
ProcessNodeType = Literal['Coder', 'Search', 'Visualization', 'Report', 'Process', 'Refiner']


def get_state_attr(state: State | dict[str, Any], key: str, default: Any = None) -> Any:
    if isinstance(state, dict):
        return state.get(key, default)
    return getattr(state, key, default)


def hypothesis_router(state: State) -> NodeType:
    current_instruction = get_state_attr(state, "current_instruction")

    if current_instruction == "Continue the research process":
        return "Process"
    else:
        return "Hypothesis"


def QualityReview_router(state: State) -> str:
    messages = get_state_attr(state, "messages", [])
    needs_revision = get_state_attr(state, "needs_revision", False)
    revision_count = get_state_attr(state, "revision_count", 0)
    MAX_REVISIONS = 3

    if needs_revision:
        if revision_count > MAX_REVISIONS:
            return "NoteTaker"

        previous_node = messages[-2].name if len(messages) >= 2 else "NoteTaker"
        revision_routes = {
            "visualization_agent": "Visualization",
            "search_agent": "Search",
            "code_agent": "Coder",
            "report_agent": "Report"
        }
        result = revision_routes.get((str(previous_node)), "NoteTaker")
        return result

    else:
        return "NoteTaker"


def process_router(state: State) -> ProcessNodeType:
    next_step = get_state_attr(state, "next_workflow_step", "")

    valid_decisions = {"Coder", "Search", "Visualization", "Report"}

    if next_step in valid_decisions:
        return cast(ProcessNodeType, next_step)

    if next_step == "FINISH":
        return "Refiner"

    step_count = get_state_attr(state, "step_count", 0)
    if step_count > 20:
        return "Refiner"

    return "Process"


class Agent:
    def invoke(self, state):
        return {"messages": [AIMessage(content="")]}

    def get_state_updates(self, state: Any, output: Any) -> dict[str, Any]:
        return {}


class HypothesisAgent(Agent):
    def get_state_updates(self, state: Any, output: Any) -> dict[str, Any]:
        return {"hypothesis": str(output)}


class ProcessAgent(Agent):
    def get_state_updates(self, state: Any, output: Any) -> dict[str, Any]:
        return {
            "current_instruction": "",
            "next_workflow_step": "",
            "todo_list": []
        }


class QualityReviewAgent(Agent):
    def get_state_updates(self, state: Any, output: Any) -> dict[str, Any]:
        needs_revision = False
        feedback = ""

        updates: dict[str, Any] = {"needs_revision": needs_revision}

        current_count = get_state_attr(state, "revision_count", 0)
        if needs_revision:
            updates["quality_feedback"] = feedback
            updates["revision_count"] = current_count + 1
        else:
            updates["quality_feedback"] = None
            updates["revision_count"] = 0

        return updates


class ArtifactAgent(Agent):
    def __init__(self, field: str):
        self.field = field

    def get_state_updates(self, state: Any, output: Any) -> dict[str, Any]:
        current = get_state_attr(state, self.field, {})
        return {self.field: {**current, "output": str(output)}}


def agent_node(state: State, agent: Agent, name: str) -> dict[str, Any]:
    try:
        result = agent.invoke(state)
        ai_message = result["messages"][-1]
        output = ai_message.content

        current_messages = list(get_state_attr(state, "messages", []))
        updates = {
            "messages": current_messages + [ai_message],
            "last_active_agent": name
        }

        if hasattr(agent, "get_state_updates"):
            agent_updates = agent.get_state_updates(state, output)
            if agent_updates:
                updates.update(agent_updates)

        current_step = get_state_attr(state, "step_count", 0)
        updates["step_count"] = current_step + 1

        current_instruction = get_state_attr(state, "current_instruction", None)
        if current_instruction:
            completed = list(get_state_attr(state, "completed_tasks", []))
            if current_instruction not in completed:
                completed.append(current_instruction)
                updates["completed_tasks"] = completed

        return updates
    except Exception as e:
        current_messages = list(get_state_attr(state, "messages", []))
        return {
            "messages": current_messages + [AIMessage(content=f"Error: {str(e)}", name=name)],
            "last_active_agent": name
        }


def human_choice_node(state: State) -> dict[str, Any]:
    choice = "2"

    current_messages = list(get_state_attr(state, "messages", []))
    updates = {
        "messages": current_messages,
        "last_active_agent": "human"
    }

    if choice == "1":
        modification_areas = ""
        updates["messages"] = current_messages + [HumanMessage(content=f"Regenerate hypothesis. Areas: {modification_areas}")]
        updates["hypothesis"] = None
    else:
        updates["messages"] = current_messages + [HumanMessage(content="Continue the research process")]
        updates["current_instruction"] = "Continue the research process"

    return updates


def note_agent_node(state: State, agent: Agent, name: str) -> dict[str, Any]:
    try:
        current_messages = list(get_state_attr(state, "messages", []))

        head_messages: list[BaseMessage] = []
        tail_messages: list[BaseMessage] = []
        processing_messages = current_messages

        if len(current_messages) > 6:
            head_messages = list(current_messages[:2])
            tail_messages = list(current_messages[-2:])
            processing_messages = list(current_messages[2:-2])

        invoke_state = state.dict() if hasattr(state, "dict") else dict(state)
        invoke_state["messages"] = processing_messages
        output = agent.invoke(invoke_state)

        new_messages = [AIMessage(content=str(msg), name=name) for msg in output.get("messages", [])]
        messages: list[BaseMessage] = list(new_messages) if new_messages else list(processing_messages)
        combined_messages = head_messages + messages + tail_messages

        updated_state = {
            "messages": combined_messages,
            "hypothesis": str(output.get("hypothesis", "")),
            "current_instruction": str(output.get("current_instruction", "")),
            "next_workflow_step": str(output.get("next_workflow_step", "")),
            "search_artifacts": {},
            "data_viz_artifacts": {},
            "code_artifacts": {},
            "report_artifacts": {},
            "quality_feedback": str(output.get("quality_feedback", "")),
            "needs_revision": bool(output.get("needs_revision", False)),
            "last_active_agent": 'note_agent'
        }
        return updated_state
    except Exception as e:
        return _create_error_state(state, AIMessage(content=f"Unexpected error: {str(e)}", name=name), name, "Unexpected error")


def _create_error_state(state: State, error_message: AIMessage, name: str, error_type: str) -> dict[str, Any]:
    current_dict = state.dict() if hasattr(state, "dict") else dict(state)
    current_dict["messages"] = list(get_state_attr(state, "messages", [])) + [error_message]
    current_dict["last_active_agent"] = name
    return current_dict


def human_review_node(state: State) -> dict[str, Any]:
    try:
        user_input = "yes"

        updates: dict[str, Any] = {"last_active_agent": "human"}

        if user_input == 'yes':
            while True:
                req = "request"
                if req:
                    updates["messages"] = [HumanMessage(content=req)]
                    updates["needs_revision"] = True
                    break
        else:
            updates["needs_revision"] = False
            updates["revision_count"] = 0

        return updates

    except Exception as e:
        current_messages = list(get_state_attr(state, "messages", []))
        return {"messages": current_messages + [AIMessage(content=f"Error: {str(e)}", name="human_review")]}


def refiner_node(state: State, agent: Agent, name: str) -> dict[str, Any]:
    try:
        refiner_input = state.dict() if hasattr(state, "dict") else dict(state)
        refiner_input["messages"] = [HumanMessage(content="Report materials")]

        result = agent.invoke(refiner_input)
        output = result.get("messages")[-1].content

        current_messages = list(get_state_attr(state, "messages", []))
        return {
            "messages": current_messages + [AIMessage(content=output, name=name)],
            "last_active_agent": name,
        }
    except Exception as e:
        current_messages = list(get_state_attr(state, "messages", []))
        return {"messages": current_messages + [AIMessage(content=f"Error: {str(e)}", name=name)]}


class WorkflowManager:
    def __init__(self):
        self.agents = {
            "hypothesis_agent": HypothesisAgent(),
            "process_agent": ProcessAgent(),
            "visualization_agent": ArtifactAgent("data_viz_artifacts"),
            "code_agent": ArtifactAgent("code_artifacts"),
            "search_agent": ArtifactAgent("search_artifacts"),
            "report_agent": ArtifactAgent("report_artifacts"),
            "quality_review_agent": QualityReviewAgent(),
            "note_agent": Agent(),
            "refiner_agent": Agent(),
        }
        self.setup_workflow()

    def setup_workflow(self):
        self.workflow = StateGraph(State)

        def _wrap_agent_node(agent, name):
            def action(state, config=None, store=None):
                return agent_node(cast(State, state), agent, name)
            return action
        def _wrap_note_agent(agent, name):
            def action(state, config=None, store=None):
                return note_agent_node(cast(State, state), agent, name)
            return action
        def _wrap_refiner(agent, name):
            def action(state, config=None, store=None):
                return refiner_node(cast(State, state), agent, name)
            return action

        self.workflow.add_node("Hypothesis", _wrap_agent_node(self.agents["hypothesis_agent"], "hypothesis_agent"))
        self.workflow.add_node("Process", _wrap_agent_node(self.agents["process_agent"], "process_agent"))
        self.workflow.add_node("Visualization", _wrap_agent_node(self.agents["visualization_agent"], "visualization_agent"))
        self.workflow.add_node("Search", _wrap_agent_node(self.agents["search_agent"], "search_agent"))
        self.workflow.add_node("Coder", _wrap_agent_node(self.agents["code_agent"], "code_agent"))
        self.workflow.add_node("Report", _wrap_agent_node(self.agents["report_agent"], "report_agent"))
        self.workflow.add_node("QualityReview", _wrap_agent_node(self.agents["quality_review_agent"], "quality_review_agent"))
        self.workflow.add_node("NoteTaker", _wrap_note_agent(self.agents["note_agent"], "note_agent"))
        self.workflow.add_node("HumanChoice", human_choice_node)
        self.workflow.add_node("HumanReview", human_review_node)
        self.workflow.add_node("Refiner", _wrap_refiner(self.agents["refiner_agent"], "refiner_agent"))

        self.workflow.add_edge(START, "Hypothesis")
        self.workflow.add_edge("Hypothesis", "HumanChoice")

        self.workflow.add_conditional_edges(
            "HumanChoice",
            hypothesis_router,
            {
                "Hypothesis": "Hypothesis",
                "Process": "Process"
            }
        )

        self.workflow.add_conditional_edges(
            "Process",
            process_router,
            {
                "Coder": "Coder",
                "Search": "Search",
                "Visualization": "Visualization",
                "Report": "Report",
                "Process": "Process",
                "Refiner": "Refiner",
            }
        )

        for member in ["Visualization", 'Search', 'Coder', 'Report']:
            self.workflow.add_edge(member, "QualityReview")

        self.workflow.add_conditional_edges(
            "QualityReview",
            QualityReview_router,
            {
                'Visualization': "Visualization",
                'Search': "Search",
                'Coder': "Coder",
                'Report': "Report",
                'NoteTaker': "NoteTaker",
            }
        )

        self.workflow.add_edge("NoteTaker", "Process")
        self.workflow.add_edge("Refiner", "HumanReview")

        self.workflow.add_conditional_edges(
            "HumanReview",
            lambda state: "Process" if state and getattr(state, "needs_revision", False) else "END",
            {
                "Process": "Process",
                "END": END
            }
        )

        self.graph = self.workflow.compile()

    def get_graph(self):
        return self.graph


graph = WorkflowManager().get_graph()
