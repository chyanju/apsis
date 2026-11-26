from collections.abc import AsyncIterable
from typing import Any

from agent_framework import (
    Agent,
    AgentExecutorRequest,
    AgentExecutorResponse,
    AgentResponse,
    BaseChatClient,
    ChatResponse,
    Executor,
    Message,
    WorkflowBuilder,
    WorkflowContext,
    handler,
)
from agent_framework_orchestrations import HandoffAgentExecutor, HandoffConfiguration


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


class RefundExecutor(Executor):
    @handler
    async def on_request(
        self,
        request: AgentExecutorRequest,
        ctx: WorkflowContext[AgentExecutorResponse],
    ) -> None:
        resp = AgentResponse(messages=[Message(role="assistant", contents=["refund processed"])])
        await ctx.send_message(
            AgentExecutorResponse(
                executor_id=self.id,
                agent_response=resp,
                full_conversation=list(request.messages),
            )
        )

    @handler
    async def on_broadcast(
        self,
        prior: AgentExecutorResponse,
        ctx: WorkflowContext[AgentExecutorResponse],
    ) -> None:
        return None


triage = _agent("triage_agent", "Coordinator that triages customer-support requests.")
order = _agent("order_agent", "Specialist that answers order-status questions.")
support = _agent("support_agent", "Specialist that handles general support requests.")

triage_node = HandoffAgentExecutor(
    agent=triage,
    handoffs=[
        HandoffConfiguration(target="refund_agent", description="Process a refund."),
        HandoffConfiguration(target="order_agent", description="Answer order-status questions."),
        HandoffConfiguration(target="support_agent", description="Handle general support."),
    ],
    is_start_agent=True,
)
order_node = HandoffAgentExecutor(agent=order, handoffs=[HandoffConfiguration(target="triage_agent")])
support_node = HandoffAgentExecutor(agent=support, handoffs=[HandoffConfiguration(target="triage_agent")])

refund_node = RefundExecutor(id="refund_agent")

_participants = [triage_node, refund_node, order_node, support_node]
_builder = WorkflowBuilder(name="customer_support_handoff", start_executor=triage_node)
for _node in _participants:
    _targets = [n for n in _participants if n.id != _node.id]
    if len(_targets) > 1:
        _builder = _builder.add_fan_out_edges(_node, _targets)
    elif len(_targets) == 1:
        _builder = _builder.add_edge(_node, _targets[0])

workflow = _builder.build()
