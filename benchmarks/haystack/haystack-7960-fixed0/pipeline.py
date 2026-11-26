from typing import List

from haystack import Pipeline, component
from haystack.components.joiners.branch import BranchJoiner
from haystack.components.routers.conditional_router import ConditionalRouter


@component
class PromptBuilder:
    @component.output_types(action=List[str])
    def run(self, messages: List[str]):
        return {"action": ["search", "some-query"]}


@component
class Concat:
    @component.output_types(messages=List[str])
    def run(self, observation: str):
        return {"messages": [observation]}


def build() -> Pipeline:
    router = ConditionalRouter(
        [
            {
                "condition": "{{'search' in action[0]}}",
                "output": "{{action[1]}}",
                "output_type": str,
                "output_name": "search",
            },
            {
                "condition": "{{'finish' in action[0]}}",
                "output": "{{action[1]}}",
                "output_type": str,
                "output_name": "finish",
            },
        ]
    )

    p = Pipeline()
    p.add_component("main_input", BranchJoiner(List[str]))
    p.add_component("builder", PromptBuilder())
    p.add_component("router", router)
    p.add_component("concat", Concat())

    p.connect("main_input.value", "builder.messages")
    p.connect("builder.action", "router.action")
    p.connect("router.search", "concat.observation")
    p.connect("concat.messages", "main_input.value")
    return p


pipeline = build()
