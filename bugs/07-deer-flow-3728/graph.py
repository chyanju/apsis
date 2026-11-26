# Derived from DeerFlow (github.com/bytedance/deer-flow, MIT) and modified; license text in LICENSE.
"""The lead agent of DeerFlow with its thread-data middleware, run with the config the gateway's `build_run_config`
builds for each shape of request it accepts. The other middleware of the lead agent read the thread id the same
way; the model is replaced by one that answers with constants."""

from collections.abc import Mapping
from typing import Any, NotRequired

from langchain.agents import AgentState, create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langgraph.config import get_config
from langgraph.runtime import Runtime

# backend/packages/harness/deerflow/agents/middlewares/thread_data_middleware.py


class ThreadDataMiddlewareState(AgentState):
    thread_data: NotRequired[dict | None]


class ThreadDataMiddleware(AgentMiddleware[ThreadDataMiddlewareState]):
    """Create thread data directories for each thread execution."""

    state_schema = ThreadDataMiddlewareState

    def __init__(self, base_dir: str = ".deer-flow"):
        super().__init__()
        self._base_dir = base_dir

    def _get_thread_paths(self, thread_id: str) -> dict[str, str]:
        return {
            "workspace_path": f"{self._base_dir}/threads/{thread_id}/user-data/workspace",
            "uploads_path": f"{self._base_dir}/threads/{thread_id}/user-data/uploads",
            "outputs_path": f"{self._base_dir}/threads/{thread_id}/user-data/outputs",
        }

    def before_agent(self, state: ThreadDataMiddlewareState, runtime: Runtime) -> dict | None:
        context = runtime.context or {}
        thread_id = context.get("thread_id")
        if thread_id is None:
            config = get_config()
            thread_id = config.get("configurable", {}).get("thread_id")
        if thread_id is None:
            raise ValueError("Thread ID is required in runtime context or config.configurable")
        return {"thread_data": self._get_thread_paths(thread_id)}


# backend/app/gateway/services.py


def build_run_config(thread_id: str, request_config: dict[str, Any] | None, metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Build a RunnableConfig dict for the agent."""
    config: dict[str, Any] = {"recursion_limit": 100}
    if request_config:
        # LangGraph >= 0.6.0 introduced ``context`` as the preferred way to
        # pass thread-level data and rejects requests that include both
        # ``configurable`` and ``context``.  If the caller already sends
        # ``context``, honour it and skip our own ``configurable`` dict.
        if "context" in request_config:
            context_value = request_config["context"]
            if context_value is None:
                context = {}
            elif isinstance(context_value, Mapping):
                context = dict(context_value)
            else:
                raise ValueError("request config 'context' must be a mapping or null.")
            config["context"] = context
        else:
            configurable = {"thread_id": thread_id}
            configurable.update(request_config.get("configurable", {}))
            config["configurable"] = configurable
        for k, v in request_config.items():
            if k not in ("configurable", "context"):
                config[k] = v
    else:
        config["configurable"] = {"thread_id": thread_id}
    if metadata:
        config.setdefault("metadata", {}).update(metadata)
    return config


class ToolModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


lead_agent = create_agent(ToolModel(messages=iter([])), tools=[], middleware=[ThreadDataMiddleware()])

# the request shapes the gateway accepts: none, the older `configurable`, the LangGraph 0.6 `context`, and both
REQUESTS = [
    None,
    {"configurable": {"user_id": "u-1"}},
    {"context": {"user_id": "u-1", "thinking_enabled": True}},
    {"context": {"user_id": "u-1"}, "configurable": {"thread_id": "T-42"}},
]
runs = [(lead_agent, build_run_config("T-42", request, None)) for request in REQUESTS]
