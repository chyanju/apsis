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
        self._stores = {}
        self._checkpointer = None
        self._deep_agents = {}

    def _get_or_create_store(self, thread_id: str):
        # each thread gets its own store, so one request's /memories/ are not another's
        if thread_id not in self._stores:
            self._stores[thread_id] = InMemoryStore()
        return self._stores[thread_id]

    def _get_or_create_checkpointer(self):
        if self._checkpointer is None:
            self._checkpointer = MemorySaver()
        return self._checkpointer

    def _build_deep_agent(self, thread_id: str):
        return create_deep_agent(
            model=ToolModel(messages=iter([])),
            tools=[execute_trade],
            system_prompt="You trade on behalf of the account owner.",
            store=self._get_or_create_store(thread_id),
            checkpointer=self._get_or_create_checkpointer(),
            backend=make_backend,
            interrupt_on={"execute_trade": True},  # a person approves every trade
        )

    def get_deep_agent(self, thread_id: str):
        if thread_id not in self._deep_agents:
            self._deep_agents[thread_id] = self._build_deep_agent(thread_id)
        return self._deep_agents[thread_id]

    async def invoke_deep_agent(self, message: str, thread_id: str | None = None):
        if thread_id is None:
            thread_id = str(uuid.uuid4())
        agent = self.get_deep_agent(thread_id)
        return await agent.ainvoke({"messages": [message]}, config={"configurable": {"thread_id": thread_id}})

    async def resume_with_decisions(self, decisions: list, thread_id: str | None = None):
        # the thread to resume is never taken from the producer's own state
        if thread_id is None:
            raise ValueError("resume_with_decisions() requires an explicit thread_id")
        agent = self.get_deep_agent(thread_id)
        config = {"configurable": {"thread_id": thread_id}}
        return await agent.ainvoke(Command(resume={"decisions": decisions}), config=config)

    async def approve_all_interrupts(self, result: dict, thread_id: str | None = None):
        requests = result["__interrupt__"][0].value.get("action_requests", [])
        return await self.resume_with_decisions([{"type": "approve"} for _ in requests], thread_id)

producer = DeepAgentChannelProducer()

# the graphs the producer runs two requests on, from different accounts
runs = [producer.get_deep_agent("account-a"), producer.get_deep_agent("account-b")]

# the producer with the runs of two requests, each waiting for the approval of a trade
serving = {
    "host": producer,
    "runs": [(graph, {"configurable": {"thread_id": thread}}) for graph, thread in zip(runs, ("account-a", "account-b"))],
}
