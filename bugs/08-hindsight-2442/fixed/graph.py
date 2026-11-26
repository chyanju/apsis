# Derived from Hindsight (github.com/vectorize-io/hindsight, MIT) and modified; license text in LICENSE.
"""The memory tools of hindsight-langgraph after the fix, built once at startup without a bank: each call resolves
the bank from the run's config. The Hindsight client is replaced by one that answers with constants."""

from typing import Any, Optional

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool
from langgraph.prebuilt import create_react_agent


class Hindsight:
    """Stands for `hindsight_client.Hindsight`."""

    async def aretain(self, **kwargs):
        return {"success": True}

    async def arecall(self, **kwargs):
        return {"results": []}

    async def areflect(self, **kwargs):
        return {"text": ""}


class HindsightError(Exception):
    pass


# hindsight-integrations/langgraph/hindsight_langgraph/tools.py


def _resolve_bank_id(bank_id: Optional[str], config: Optional[RunnableConfig], bank_id_from_config: str) -> str:
    if bank_id:
        return bank_id
    if config:
        configurable = config.get("configurable", {})
        resolved_bank_id = configurable.get(bank_id_from_config)
        if resolved_bank_id:
            return resolved_bank_id
    raise HindsightError(
        f"No bank_id available for Hindsight tool. Pass bank_id or set config['configurable']['{bank_id_from_config}']."
    )


def create_hindsight_tools(
    *,
    bank_id: Optional[str] = None,
    client: Optional[Hindsight] = None,
    budget: Optional[str] = None,
    max_tokens: Optional[int] = None,
    bank_id_from_config: str = "user_id",
    include_retain: bool = True,
    include_recall: bool = True,
    include_reflect: bool = True,
) -> list[BaseTool]:
    """Create Hindsight memory tools for a LangGraph agent."""
    resolved_client = client or Hindsight()
    effective_budget = budget if budget is not None else "mid"
    effective_max_tokens = max_tokens if max_tokens is not None else 4096

    tools: list = []

    if include_retain:

        @tool
        async def hindsight_retain(content: str, config: RunnableConfig) -> str:
            """Store information to long-term memory for later retrieval.

            Args:
                content: The information to store in memory.
            """
            try:
                resolved_bank_id = _resolve_bank_id(bank_id, config, bank_id_from_config)
                retain_kwargs: dict[str, Any] = {"bank_id": resolved_bank_id, "content": content}
                await resolved_client.aretain(**retain_kwargs)
                return "Memory stored successfully."
            except HindsightError:
                raise
            except Exception as e:
                raise HindsightError(f"Retain failed: {e}") from e

        tools.append(hindsight_retain)

    if include_recall:

        @tool
        async def hindsight_recall(query: str, config: RunnableConfig) -> str:
            """Search long-term memory for relevant information.

            Args:
                query: What to search for in memory.
            """
            try:
                resolved_bank_id = _resolve_bank_id(bank_id, config, bank_id_from_config)
                recall_kwargs: dict[str, Any] = {
                    "bank_id": resolved_bank_id,
                    "query": query,
                    "budget": effective_budget,
                    "max_tokens": effective_max_tokens,
                }
                response = await resolved_client.arecall(**recall_kwargs)
                return "\n".join(f"{i}. {r}" for i, r in enumerate(response["results"], 1)) or "No relevant memories found."
            except HindsightError:
                raise
            except Exception as e:
                raise HindsightError(f"Recall failed: {e}") from e

        tools.append(hindsight_recall)

    if include_reflect:

        @tool
        async def hindsight_reflect(query: str, config: RunnableConfig) -> str:
            """Synthesize a reasoned answer from long-term memories.

            Args:
                query: The question to reflect on.
            """
            try:
                resolved_bank_id = _resolve_bank_id(bank_id, config, bank_id_from_config)
                reflect_kwargs: dict[str, Any] = {"bank_id": resolved_bank_id, "query": query, "budget": effective_budget}
                response = await resolved_client.areflect(**reflect_kwargs)
                return response["text"] or "No relevant memories found."
            except HindsightError:
                raise
            except Exception as e:
                raise HindsightError(f"Reflect failed: {e}") from e

        tools.append(hindsight_reflect)

    return tools


class ToolModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


# the README's multi-tenant pattern after the fix: no bank at startup, the user id of each request selects it
tools = create_hindsight_tools()
agent = create_react_agent(ToolModel(messages=iter([])), tools=tools)

runs = [(agent, {"configurable": {"user_id": "user-alice"}}), (agent, {"configurable": {"user_id": "user-bob"}})]
