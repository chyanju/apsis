from typing_extensions import Never

from agent_framework import (
    Executor,
    WorkflowBuilder,
    WorkflowContext,
    WorkflowExecutor,
    handler,
)


class Drafter(Executor):
    @handler
    async def run(self, draft: str, ctx: WorkflowContext[str]) -> None:
        await ctx.send_message(draft + " [revised]")


class Critic(Executor):
    @handler
    async def run(self, draft: str, ctx: WorkflowContext[str]) -> None:
        await ctx.send_message(draft)


_drafter = Drafter(id="drafter")
_critic = Critic(id="critic")

refinement_subworkflow = (
    WorkflowBuilder(start_executor=_drafter)
    .add_edge(_drafter, _critic)
    .add_edge(_critic, _drafter)
    .build()
)


class Intake(Executor):
    @handler
    async def run(self, topic: str, ctx: WorkflowContext[str]) -> None:
        await ctx.send_message(topic)


class Publish(Executor):
    @handler
    async def run(self, result: str, ctx: WorkflowContext[Never, str]) -> None:
        await ctx.yield_output(result)


_intake = Intake(id="intake")
_refine = WorkflowExecutor(refinement_subworkflow, id="refine_loop")
_publish = Publish(id="publish")

workflow = (
    WorkflowBuilder(start_executor=_intake)
    .add_edge(_intake, _refine)
    .add_edge(_refine, _publish)
    .build()
)
