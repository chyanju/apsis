from llama_index.core.agent.workflow import FunctionAgent
from llama_index.core.llms.mock import MockFunctionCallingLLM
from llama_index.core.workflow import Context, HumanResponseEvent, InputRequiredEvent


async def dangerous_task(ctx: Context, action: str) -> str:
    """Run an action once a person approves it."""
    response = await ctx.wait_for_event(
        HumanResponseEvent,
        waiter_event=InputRequiredEvent(prefix=f"Approve {action}? "),
    )
    return "done" if response.response.strip().lower() == "yes" else "aborted"


workflow = FunctionAgent(
    tools=[dangerous_task],
    llm=MockFunctionCallingLLM(),
    system_prompt="You run tasks once a person approves them.",
)
