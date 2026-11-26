import asyncio
from typing import List, Sequence

from autogen_core.base import CancellationToken

from autogen_agentchat.agents import AssistantAgent, BaseChatAgent
from autogen_agentchat.base import Response
from autogen_agentchat.messages import ChatMessage, HandoffMessage, TextMessage
from autogen_agentchat.teams import Swarm
from autogen_agentchat.task import HandoffTermination, MaxMessageTermination


class _PlaceholderModelClient:
    def __init__(self, model: str = "gpt-4o") -> None:
        self.model = model


class UserProxyAgent(BaseChatAgent):
    def __init__(self, name: str) -> None:
        super().__init__(name, "A human user.")

    @property
    def produced_message_types(self) -> List[type[ChatMessage]]:
        return [TextMessage, HandoffMessage]

    async def on_messages(
        self, messages: Sequence[ChatMessage], cancellation_token: CancellationToken
    ) -> Response:
        user_input = await asyncio.get_event_loop().run_in_executor(None, input, "User: ")
        last_handoff_source = None
        for message in reversed(messages):
            if isinstance(message, HandoffMessage) and message.target == self.name:
                last_handoff_source = message.source
                break
        text_message = TextMessage(content=user_input, source=self.name)
        handoff_message = HandoffMessage(
            content=user_input,
            source=self.name,
            target=last_handoff_source,
        )
        return Response(chat_message=handoff_message, inner_messages=[text_message])

    async def on_reset(self, cancellation_token: CancellationToken) -> None:
        return None


model_client = _PlaceholderModelClient(model="gpt-4o")

triage = AssistantAgent(
    "triage",
    model_client=model_client,
    handoffs=["refunds", "user"],
    system_message="Route the customer to the right specialist, or hand back to the user.",
)

refunds = AssistantAgent(
    "refunds",
    model_client=model_client,
    handoffs=["user"],
    system_message="You process refund requests, then hand control back to the user.",
)

user = UserProxyAgent("user")

termination = HandoffTermination(target="user") | MaxMessageTermination(10)

workflow = Swarm([triage, refunds, user], termination_condition=termination)
