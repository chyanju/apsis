from typing import Any, Dict, List, Optional

from haystack import Pipeline, component


@component
class Retriever:
    @component.output_types(documents=List[str])
    def run(
        self,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
        top_k: Optional[int] = None,
        scale_score: Optional[bool] = None,
    ):
        return {"documents": [query]}


@component
class PromptBuilder:
    @component.output_types(prompt=str)
    def run(self, documents: Any, query: str = "", template: Optional[str] = None):
        return {"prompt": f"{query} {documents}"}


@component
class Generator:
    @component.output_types(replies=str)
    def run(self, prompt: str):
        return {"replies": prompt}


def build() -> Pipeline:
    p = Pipeline()
    p.add_component("retriever", Retriever())
    p.add_component("prompt_builder", PromptBuilder())
    p.add_component("generator", Generator())
    p.connect("retriever.documents", "prompt_builder.documents")
    p.connect("prompt_builder.prompt", "generator.prompt")
    return p


pipeline = build()
