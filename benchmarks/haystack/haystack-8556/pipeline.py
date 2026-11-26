from haystack import Pipeline, component
from haystack.components.routers import ConditionalRouter


@component
class QuestionSource:
    @component.output_types(question=str)
    def run(self, text: str):
        return {"question": text}


@component
class BranchHandler:
    @component.output_types(answer=str)
    def run(self, query: str):
        return {"answer": query}


def build() -> Pipeline:
    routes = [
        {
            "condition": '{{path == "rag"}}',
            "output": "{{question}}",
            "output_name": "normal",
            "output_type": str,
        },
        {
            "condition": '{{path == "followup_short"}}',
            "output": "{{question}}",
            "output_name": "followup_short",
            "output_type": str,
        },
        {
            "condition": '{{path == "followup_elaborate"}}',
            "output": "{{question}}",
            "output_name": "followup_elaborate",
            "output_type": str,
        },
        {
            "condition": "{{ True }}",
            "output": "{{ question }}",
            "output_name": "fallback",
            "output_type": str,
        },
    ]

    p = Pipeline()
    p.add_component("source", QuestionSource())
    p.add_component("router", ConditionalRouter(routes=routes))
    p.add_component("normal_handler", BranchHandler())
    p.add_component("fallback_handler", BranchHandler())

    p.connect("source.question", "router.question")
    p.connect("router.normal", "normal_handler.query")
    p.connect("router.fallback", "fallback_handler.query")
    return p


pipeline = build()
