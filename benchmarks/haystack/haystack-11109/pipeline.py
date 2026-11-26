from typing import List, Optional

from haystack import Pipeline, component
from haystack.components.joiners.branch import BranchJoiner
from haystack.components.routers.conditional_router import ConditionalRouter


@component
class PlanningAgent:
    @component.output_types(messages=List[str])
    def run(self, query: str, streaming_callback: Optional[object] = None):
        return {"messages": [query]}


@component
class ExecutionAgent:
    @component.output_types(result=str)
    def run(self, messages: Optional[List[str]] = None, streaming_callback: Optional[object] = None):
        return {"result": str(messages)}


def build() -> Pipeline:
    router = ConditionalRouter(
        [
            {
                "condition": "{{needs_plan}}",
                "output": "{{query}}",
                "output_type": str,
                "output_name": "plan",
            },
            {
                "condition": "{{not needs_plan}}",
                "output": "{{[query]}}",
                "output_type": List[str],
                "output_name": "exec",
            },
        ]
    )
    p = Pipeline()
    p.add_component("router", router)
    p.add_component("planner", PlanningAgent())
    p.add_component("joiner", BranchJoiner(type_=List[str]))
    p.add_component("executor", ExecutionAgent())

    p.connect("router.plan", "planner.query")
    p.connect("router.exec", "joiner.value")
    p.connect("planner.messages", "joiner.value")
    p.connect("joiner.value", "executor.messages")
    return p


pipeline = build()
