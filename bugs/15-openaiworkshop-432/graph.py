# Derived from OpenAIWorkshop (github.com/microsoft/OpenAIWorkshop, MIT) and modified; license text in LICENSE.
"""The reflection loop of `Agent.chat_async` in reflection_agent.py, written as an Agent Framework workflow: each
step of the loop is an executor, and the attempt count travels with the draft. The project runs the steps in a Python
`for` loop; the primary agent's and the reviewer's replies are replaced by constants."""

from dataclasses import dataclass

from typing_extensions import Never

from agent_framework import Executor, WorkflowBuilder, WorkflowContext, handler

MAX_REFINEMENTS = 2


@dataclass
class Draft:
    prompt: str
    response: str
    attempt: int  # refinements made so far


@dataclass
class Review:
    draft: Draft
    review: str


def _is_approved(review: str) -> bool:
    """Check if the reviewer approved the response."""
    return "APPROVE" in review.upper()


class PrimaryAgent(Executor):
    """Step 1: the primary agent generates a response."""

    @handler
    async def answer(self, prompt: str, ctx: WorkflowContext[Draft]) -> None:
        response = "Your account is active."
        await ctx.send_message(Draft(prompt, response, 0))


class Reviewer(Executor):
    """Step 2: the reviewer evaluates a response."""

    @handler
    async def review(self, draft: Draft, ctx: WorkflowContext[Review]) -> None:
        review = "Missing context."
        await ctx.send_message(Review(draft, review))


class Refiner(Executor):
    """Step 3: the primary agent refines the response; it is re-reviewed if this is not the last attempt."""

    @handler
    async def refine(self, review: Review, ctx: WorkflowContext[Draft, str]) -> None:
        attempt = review.draft.attempt
        response = f"Improved: {review.draft.response}"
        # Re-review if not last attempt
        if attempt < MAX_REFINEMENTS - 1:
            await ctx.send_message(Draft(review.draft.prompt, response, attempt + 1))
        else:
            await ctx.yield_output(response)


class Deliver(Executor):
    """The response the reviewer approved is returned."""

    @handler
    async def deliver(self, review: Review, ctx: WorkflowContext[Never, str]) -> None:
        await ctx.yield_output(review.draft.response)


def approved(review: Review) -> bool:
    return _is_approved(review.review)


def rejected(review: Review) -> bool:
    return not _is_approved(review.review)


primary = PrimaryAgent(id="primary_agent")
reviewer = Reviewer(id="reviewer_agent")
refiner = Refiner(id="refine")
deliver = Deliver(id="deliver")

workflow = (
    WorkflowBuilder(start_executor=primary)
    .add_edge(primary, reviewer)
    .add_edge(reviewer, deliver, condition=approved)
    .add_edge(reviewer, refiner, condition=rejected)
    .add_edge(refiner, reviewer)
    .build()
)
