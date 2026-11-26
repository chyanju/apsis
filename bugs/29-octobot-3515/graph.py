import uuid

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command


class ToolModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def execute_trade(symbol: str) -> str:
    """Place the trade the agent decided on."""
    return f"order placed for {symbol}"


def make_backend(runtime):
    # /memories/ lives in the long-term store, everything else in the run's state
    return CompositeBackend(default=StateBackend(runtime), routes={"/memories/": StoreBackend(runtime)})


class DeepAgentChannelProducer:
    """One producer per channel for the life of the process; it serves every request on the channel."""

    def __init__(self):
        self._store = None
        self._checkpointer = None
        self._deep_agent = None
        self._current_thread_id = None

    def _get_or_create_store(self):
        if self._store is None:
            self._store = InMemoryStore()
        return self._store

    def _get_or_create_checkpointer(self):
        if self._checkpointer is None:
            self._checkpointer = MemorySaver()
        return self._checkpointer

    def _build_deep_agent(self):
        return create_deep_agent(
            model=ToolModel(messages=iter([])),
            tools=[execute_trade],
            system_prompt="You trade on behalf of the account owner.",
            store=self._get_or_create_store(),
            checkpointer=self._get_or_create_checkpointer(),
            backend=make_backend,
            interrupt_on={"execute_trade": True},  # a person approves every trade
        )

    def get_deep_agent(self):
        if self._deep_agent is None:
            self._deep_agent = self._build_deep_agent()
        return self._deep_agent

    async def invoke_deep_agent(self, message: str, thread_id: str | None = None):
        agent = self.get_deep_agent()
        if thread_id is None:
            thread_id = str(uuid.uuid4())
        self._current_thread_id = thread_id
        return await agent.ainvoke({"messages": [message]}, config={"configurable": {"thread_id": thread_id}})

    async def resume_with_decisions(self, decisions: list, thread_id: str | None = None):
        agent = self.get_deep_agent()
        thread_id = thread_id or self._current_thread_id
        config = {"configurable": {"thread_id": thread_id}}
        return await agent.ainvoke(Command(resume={"decisions": decisions}), config=config)

    async def approve_all_interrupts(self, result: dict, thread_id: str | None = None):
        requests = result["__interrupt__"][0].value.get("action_requests", [])
        return await self.resume_with_decisions([{"type": "approve"} for _ in requests], thread_id)


producer = DeepAgentChannelProducer()

# the graphs the producer runs two requests on, from different accounts
runs = [producer.get_deep_agent(), producer.get_deep_agent()]

# the producer with the runs of two requests, each waiting for the approval of a trade
serving = {
    "host": producer,
    "runs": [(graph, {"configurable": {"thread_id": thread}}) for graph, thread in zip(runs, ("account-a", "account-b"))],
}
