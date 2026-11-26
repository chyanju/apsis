from typing import Dict, List

from haystack import Pipeline, component
from haystack.components.routers.conditional_router import ConditionalRouter


@component
class PayloadBuilder:
    @component.output_types(payload=Dict)
    def run(self, streams: List[int] = [], query: str = ""):
        return {"payload": {"streams": streams, "query": query}}


def build() -> Pipeline:
    router = ConditionalRouter(
        [
            {
                "condition": "{{streams|length < 2}}",
                "output": "{{query}}",
                "output_type": str,
                "output_name": "query",
            },
            {
                "condition": "{{streams|length >= 2}}",
                "output": "{{streams}}",
                "output_type": List[int],
                "output_name": "streams",
            },
        ]
    )
    p = Pipeline()
    p.add_component("router", router)
    p.add_component("payload_builder", PayloadBuilder())
    p.connect("router.query", "payload_builder.query")
    p.connect("router.streams", "payload_builder.streams")
    return p


pipeline = build()
