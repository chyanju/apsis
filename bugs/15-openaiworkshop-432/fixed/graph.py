# Derived from OpenAIWorkshop (github.com/microsoft/OpenAIWorkshop, MIT) and modified; license text in LICENSE.
"""The reflection loop of `Agent.chat_async` after the fix, written as an Agent Framework workflow: every refinement
goes back to the reviewer, and the response is returned after the reviewer approves it or the attempts run out. The
primary agent's and the reviewer's replies are replaced by constants."""

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
    return review.strip().upper() == "APPROVE"


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
    """Step 3: the primary agent refines the response."""

    @handler
    async def refine(self, review: Review, ctx: WorkflowContext[Draft]) -> None:
        response = f"Improved: {review.draft.response}"
        # Every candidate response must pass through the reviewer, including
        # the final refinement allowed by the configured attempt budget.
        await ctx.send_message(Draft(review.draft.prompt, response, review.draft.attempt + 1))


class Deliver(Executor):
    """The reviewed response is returned."""

    @handler
    async def deliver(self, review: Review, ctx: WorkflowContext[Never, str]) -> None:
        await ctx.yield_output(review.draft.response)


def done(review: Review) -> bool:
    return _is_approved(review.review) or review.draft.attempt >= MAX_REFINEMENTS


def refine_again(review: Review) -> bool:
    return not done(review)


primary = PrimaryAgent(id="primary_agent")
reviewer = Reviewer(id="reviewer_agent")
refiner = Refiner(id="refine")
deliver = Deliver(id="deliver")

workflow = (
    WorkflowBuilder(start_executor=primary)
    .add_edge(primary, reviewer)
    .add_edge(reviewer, deliver, condition=done)
    .add_edge(reviewer, refiner, condition=refine_again)
    .add_edge(refiner, reviewer)
    .build()
)
