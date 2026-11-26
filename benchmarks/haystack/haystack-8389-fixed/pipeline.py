from typing import List, Optional

from haystack import Document, Pipeline, component
from haystack.core.component.types import Variadic


@component
class PromptBuilder:
    @component.output_types(prompt=str)
    def run(self, query: str):
        return {"prompt": f"Extract a metadata filter from: {query}"}


@component
class FilterLLM:
    @component.output_types(replies=List[str])
    def run(self, prompt: str):
        return {"replies": ["{}"]}


@component
class FilterParser:
    @component.output_types(filters=dict)
    def run(self, replies: List[str]):
        if replies and replies[0] != "{}":
            return {"filters": {"field": "meta.year"}}
        return {"filters": {}}


@component
class FilteredRetriever:
    @component.output_types(documents=List[Document])
    def run(self, filters: dict):
        return {"documents": [Document(content="filtered" if filters else "unfiltered")]}


@component
class DocumentJoiner:
    @component.output_types(documents=List[Document])
    def run(self, documents: Variadic[List[Document]], top_k: Optional[int] = None):
        merged: List[Document] = []
        for docs in documents:
            merged.extend(docs)
        return {"documents": merged}


def build() -> Pipeline:
    p = Pipeline()
    p.add_component("prompt_builder", PromptBuilder())
    p.add_component("llm", FilterLLM())
    p.add_component("filter_parser", FilterParser())
    p.add_component("filtered_retriever", FilteredRetriever())
    p.add_component("joiner", DocumentJoiner())

    p.connect("prompt_builder.prompt", "llm.prompt")
    p.connect("llm.replies", "filter_parser.replies")
    p.connect("filter_parser.filters", "filtered_retriever.filters")
    p.connect("filtered_retriever.documents", "joiner.documents")
    return p


pipeline = build()
