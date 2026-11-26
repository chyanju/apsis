from dataclasses import dataclass

from agent_framework import (
    Executor,
    WorkflowBuilder,
    WorkflowContext,
    WorkflowExecutor,
    handler,
)

CURRENCY_KEY = "report_currency"


@dataclass
class ResearchTask:
    ticker: str


@dataclass
class Fundamentals:
    ticker: str
    pe_ratio: float


@dataclass
class Sentiment:
    ticker: str
    score: float


@dataclass
class AnalystReport:
    ticker: str
    text: str


class DispatchExecutor(Executor):
    @handler
    async def run(self, task: ResearchTask, ctx: WorkflowContext[ResearchTask]) -> None:
        await ctx.send_message(task)


class FundamentalsExecutor(Executor):
    @handler
    async def run(self, task: ResearchTask, ctx: WorkflowContext[Fundamentals]) -> None:
        currency = ctx.get_state(CURRENCY_KEY)
        _ = currency
        await ctx.send_message(Fundamentals(ticker=task.ticker, pe_ratio=18.5))


class SentimentExecutor(Executor):
    @handler
    async def run(self, task: ResearchTask, ctx: WorkflowContext[Sentiment]) -> None:
        await ctx.send_message(Sentiment(ticker=task.ticker, score=0.7))


class ComposeExecutor(Executor):
    @handler
    async def run(
        self,
        parts: list[Fundamentals | Sentiment],
        ctx: WorkflowContext[AnalystReport, AnalystReport],
    ) -> None:
        ticker = parts[0].ticker
        await ctx.yield_output(AnalystReport(ticker=ticker, text="analyst report"))


def _build_research_subworkflow():
    dispatch = DispatchExecutor(id="dispatch")
    fundamentals = FundamentalsExecutor(id="fundamentals")
    sentiment = SentimentExecutor(id="sentiment")
    compose = ComposeExecutor(id="compose")
    return (
        WorkflowBuilder(name="research-sub", start_executor=dispatch, output_from=[compose])
        .add_fan_out_edges(dispatch, [fundamentals, sentiment])
        .add_fan_in_edges([fundamentals, sentiment], compose)
        .build()
    )


class ParentIntake(Executor):
    @handler
    async def run(self, task: ResearchTask, ctx: WorkflowContext[ResearchTask]) -> None:
        ctx.set_state(CURRENCY_KEY, "EUR")
        await ctx.send_message(task)


class ParentFinalize(Executor):
    @handler
    async def run(
        self, report: AnalystReport, ctx: WorkflowContext[AnalystReport, AnalystReport]
    ) -> None:
        await ctx.yield_output(report)


def _build():
    intake = ParentIntake(id="intake")
    research = WorkflowExecutor(_build_research_subworkflow(), id="research_subworkflow")
    finalize = ParentFinalize(id="finalize")
    return (
        WorkflowBuilder(name="equity-parent", start_executor=intake, output_from=[finalize])
        .add_edge(intake, research)
        .add_edge(research, finalize)
        .build()
    )


workflow = _build()
