from collections.abc import AsyncIterable
from typing import Any

from agent_framework import Agent, BaseChatClient, ChatResponse, Message
from agent_framework_orchestrations import HandoffBuilder


class ToyChatClient(BaseChatClient):
    async def _inner_get_response(self, *, messages, stream, options, **kwargs):
        if stream:
            from agent_framework import ChatResponseUpdate

            async def _stream() -> AsyncIterable[Any]:
                yield ChatResponseUpdate(role="assistant", contents=[{"type": "text", "text": "ok"}])

            return _stream()
        return ChatResponse(messages=[Message(role="assistant", contents=["ok"])], response_id="toy")


def _agent(name: str, description: str) -> Agent:
    return Agent(
        client=ToyChatClient(),
        instructions=f"You are the {name}.",
        name=name,
        description=description,
        require_per_service_call_history_persistence=True,
    )


triage = _agent("triage_agent", "Coordinator that triages customer-support requests.")
refund = _agent("refund_agent", "Specialist that processes refunds for damaged orders.")
order = _agent("order_agent", "Specialist that answers order-status questions.")
support = _agent("support_agent", "Specialist that handles general support requests.")

workflow = (
    HandoffBuilder(
        name="customer_support_handoff",
        participants=[triage, refund, order, support],
    )
    .add_handoff(triage, [refund, order, support])
    .add_handoff(refund, [triage])
    .add_handoff(order, [triage])
    .add_handoff(support, [triage])
    .with_start_agent(triage)
    .build()
)
