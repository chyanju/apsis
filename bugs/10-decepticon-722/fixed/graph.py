# Derived from Decepticon (github.com/PurpleAILAB/Decepticon, Apache-2.0) and modified; license text in LICENSE.
"""Decepticon's orchestrator after the fix: `StreamingRunnable.with_config` carries the failure count to the instance
it builds. Event emission is left out; the models are replaced by ones that answer with constants."""

from __future__ import annotations

import contextvars
from typing import Any

from deepagents import create_deep_agent
from deepagents.middleware.subagents import CompiledSubAgent
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable, RunnableBinding
from langgraph.graph import START, MessagesState, StateGraph

# packages/decepticon/decepticon/core/subagent_streaming.py

MAX_SUBAGENT_CONSECUTIVE_FAILURES = 3
_TERMINAL_MARKER = "[TERMINAL]"

_active_renderer: contextvars.ContextVar[Any] = contextvars.ContextVar("subagent_renderer", default=None)


class StreamingRunnable(RunnableBinding):
    """Wraps a compiled LangGraph agent to stream events during invoke().

    Subclasses ``RunnableBinding`` so deepagents' SubAgentMiddleware call to
    ``compiled["runnable"].with_config(...)`` reconstructs a StreamingRunnable
    (via ``self.__class__``) rather than collapsing back to the bare inner graph.
    """

    def __init__(self, runnable: Runnable | None = None, name: str | None = None, **data: Any) -> None:
        if runnable is not None and "bound" not in data:
            data["bound"] = runnable
        if name is not None and "name" not in data:
            data["name"] = name
        super().__init__(**data)
        # Pydantic BaseModel: use object.__setattr__ to attach mutable
        # per-instance state outside the declared field schema.
        object.__setattr__(self, "_consecutive_failures", 0)

    def with_config(self, config: Any = None, **kwargs: Any) -> "StreamingRunnable":
        rebound = super().with_config(config, **kwargs)
        object.__setattr__(
            rebound,
            "_consecutive_failures",
            int(getattr(self, "_consecutive_failures", 0)),
        )
        return rebound

    def _bump_failure_and_format(self, exc: BaseException) -> str:
        """Increment the failure counter; return the message body for the
        returned state. Switches to a distinct TERMINAL marker once the cap
        is reached so the orchestrator can stop re-delegating."""
        n = int(getattr(self, "_consecutive_failures", 0)) + 1
        object.__setattr__(self, "_consecutive_failures", n)
        if n >= MAX_SUBAGENT_CONSECUTIVE_FAILURES:
            return (
                f"{_TERMINAL_MARKER} subagent '{self._name}' failed {n} "
                f"consecutive times; aborting this objective. "
                f"Last error: {type(exc).__name__}: {exc}"
            )
        return f"Subagent '{self._name}' failed: {type(exc).__name__}: {exc}"

    def _reset_failures(self) -> None:
        object.__setattr__(self, "_consecutive_failures", 0)

    @property
    def _runnable(self) -> Runnable:
        return self.bound

    @property
    def _name(self) -> str:
        return self.name or (self.config or {}).get("run_name") or "subagent"

    def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
        if _active_renderer.get(None) is None:
            return self._runnable.invoke(input, config, **kwargs)
        last_state = None
        try:
            for state in self._runnable.stream(input, config=config, stream_mode="values", **kwargs):
                last_state = state
        except Exception as exc:
            error_msg = self._bump_failure_and_format(exc)
            if last_state is not None:
                last_state.setdefault("messages", []).append(AIMessage(content=error_msg))
                return last_state
            return {"messages": [AIMessage(content=error_msg)]}
        self._reset_failures()
        return last_state


class ToolModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def recon_agent():
    """Stands for the recon specialist's graph."""
    g = StateGraph(MessagesState)
    g.add_node("recon", lambda state: {"messages": [AIMessage(content="no hosts found")]})
    g.add_edge(START, "recon")
    return g.compile()


# packages/decepticon/decepticon/agents/standard/decepticon.py: each sub-agent is wrapped in StreamingRunnable
subagents = [CompiledSubAgent(name="recon", description="Reconnaissance specialist", runnable=StreamingRunnable(recon_agent(), "recon"))]
graph = create_deep_agent(model=ToolModel(messages=iter([])), tools=[], subagents=subagents)
