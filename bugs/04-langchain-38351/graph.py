from langchain.agents import create_agent
from langchain.agents.middleware.types import AgentMiddleware, ExtendedModelResponse
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.types import Command


class ToolBindFakeModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kw):
        return self


@tool
def foo(x: int) -> int:
    """A trivial tool the agent can call."""
    return x + 1


class InjectToolMessageMiddleware(AgentMiddleware):
    name = "inject_tool_msg"

    def wrap_model_call(self, request, handler):
        response = handler(request)
        ai = response.result[0]
        if isinstance(ai, AIMessage) and ai.tool_calls:
            synthetic = [
                ToolMessage(content="cached", tool_call_id=tc["id"], name=tc["name"])
                for tc in ai.tool_calls
            ]
            return ExtendedModelResponse(
                model_response=response,
                command=Command(update={"messages": synthetic}),
            )
        return response


fake = ToolBindFakeModel(messages=iter([]))
graph = create_agent(model=fake, tools=[foo], middleware=[InjectToolMessageMiddleware()])
