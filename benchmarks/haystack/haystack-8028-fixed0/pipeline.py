from typing import List

from haystack import Pipeline, component
from haystack.components.routers import ConditionalRouter
from haystack.components.routers.conditional_router import Route


@component
class TextEmbedder:
    @component.output_types(embedding=List[float])
    def run(self, text: str):
        return {"embedding": [float(len(text))]}


@component
class Retriever:
    @component.output_types(documents=List[str])
    def run(self, query_embedding: List[float]):
        return {"documents": ["doc"]}


@component
class PromptBuilder:
    @component.output_types(prompt=str)
    def run(self, documents: List[str], query: str = ""):
        return {"prompt": query + ":" + ",".join(documents)}


@component
class LLM:
    @component.output_types(replies=List[str])
    def run(self, prompt: str):
        return {"replies": [prompt]}


def build() -> Pipeline:
    routes = [
        Route(
            condition="{{ query|length > 5 }}",
            output="{{ query }}",
            output_name="ok_query",
            output_type=str,
        ),
        Route(
            condition="{{ query|length <= 5 }}",
            output="query is too short: {{ query }}",
            output_name="too_short_query",
            output_type=str,
        ),
    ]
    p = Pipeline()
    p.add_component("router", ConditionalRouter(routes=routes))
    p.add_component("text_embedder", TextEmbedder())
    p.add_component("retriever", Retriever())
    p.add_component("prompt_builder", PromptBuilder())
    p.add_component("llm", LLM())

    p.connect("router.ok_query", "text_embedder.text")
    p.connect("text_embedder.embedding", "retriever.query_embedding")
    p.connect("retriever.documents", "prompt_builder.documents")
    p.connect("prompt_builder.prompt", "llm.prompt")
    return p


pipeline = build()
