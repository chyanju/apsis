from collections.abc import AsyncIterable
from typing import Any

from agent_framework import (
    AgentExecutorResponse,
    AgentResponse,
    BaseChatClient,
    ChatResponse,
    ChatResponseUpdate,
    Message,
    WorkflowBuilder,
    WorkflowContext,
    executor,
)


class ToyChatClient(BaseChatClient):
    async def _inner_get_response(self, *, messages, stream, options, **kwargs):
        if stream:

            async def _stream() -> AsyncIterable[Any]:
                yield ChatResponseUpdate(role="assistant", contents=[{"type": "text", "text": "ok"}])

            return _stream()
        return ChatResponse(messages=[Message(role="assistant", contents=["ok"])], response_id="toy")


@executor(
    id="upper_case_executor",
    input=AgentExecutorResponse,
    output=AgentExecutorResponse,
    workflow_output=str,
)
async def upper_case(
    executor_response: AgentExecutorResponse,
    ctx: WorkflowContext[AgentExecutorResponse, str],
) -> None:
    text = executor_response.agent_response.text
    upper_message = Message(role="assistant", contents=[text.upper()])
    forwarded = AgentExecutorResponse(
        executor_id=executor_response.executor_id,
        agent_response=AgentResponse(messages=[upper_message]),
        full_conversation=[*executor_response.full_conversation, upper_message],
    )
    await ctx.send_message(forwarded)
    await ctx.yield_output(text.upper())


_client = ToyChatClient()

agent1 = _client.as_agent(
    name="ContextAgent1",
    description="First agent that adds information to context",
    instructions="Always respond with this phrase: 'User likes sky red'",
)
agent2 = _client.as_agent(
    name="ContextAgent2",
    description="Second agent that adds information to context",
    instructions="Always respond with this phrase: 'User likes sky blue'",
)
agent3 = _client.as_agent(
    name="ContextAgent3",
    description="Third agent that adds information to context",
    instructions="Always respond with this phrase: 'User likes sky green'",
)
agent4 = _client.as_agent(
    name="ContextAgent4",
    description="Fourth agent that verifies context persistence",
    instructions="Print all previous agent messages visible to you from the chat context.",
)

workflow = (
    WorkflowBuilder(
        name="ContextPersistingWorkflow",
        description="Example workflow that demonstrates context persistence across multiple steps.",
        start_executor=agent1,
        output_executors=[agent1, agent2, upper_case, agent3, agent4],
    )
    .add_chain([agent1, agent2, upper_case, agent3, agent4])
    .build()
)
