from typing import List, Optional

from haystack import Pipeline, component
from haystack.components.routers import ConditionalRouter


@component
class Llm:
    @component.output_types(replies=List[str])
    def run(self, messages: List[str]):
        return {"replies": messages}


@component
class Consumer:
    @component.output_types(valid_replies=List[str])
    def run(
        self,
        assistant_reply: Optional[List[str]] = None,
        tool_call: Optional[List[str]] = None,
    ):
        return {"valid_replies": assistant_reply or tool_call}


def build() -> Pipeline:
    routes = [
        {
            "condition": "{{ replies[0] == 'tool' }}",
            "output": "{{ replies }}",
            "output_name": "tool_call",
            "output_type": List[str],
        },
        {
            "condition": "{{ replies[0] != 'tool' }}",
            "output": "{{ replies }}",
            "output_name": "assistant_reply",
            "output_type": List[str],
        },
    ]

    p = Pipeline()
    p.add_component("llm", Llm())
    p.add_component("router", ConditionalRouter(routes=routes))
    p.add_component("consumer", Consumer())

    p.connect("llm.replies", "router.replies")
    p.connect("router.assistant_reply", "consumer.assistant_reply")
    p.connect("router.tool_call", "consumer.tool_call")
    return p


pipeline = build()
