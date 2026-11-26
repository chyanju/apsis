from typing import List

from haystack import Document, Pipeline, component
from haystack.components.builders.prompt_builder import PromptBuilder


@component
class LinkContentFetcher:
    @component.output_types(streams=List[str])
    def run(self, urls: List[str]):
        return {"streams": urls}


@component
class HTMLToDocument:
    @component.output_types(documents=List[Document])
    def run(self, sources: List[str]):
        return {"documents": [Document(content=s) for s in sources]}


@component
class DocumentSplitter:
    @component.output_types(documents=List[Document])
    def run(self, documents: List[Document]):
        return {"documents": documents}


@component
class TransformersSimilarityRanker:
    @component.output_types(documents=List[Document])
    def run(self, query: str, documents: List[Document]):
        return {"documents": documents}


@component
class GPTGenerator:
    @component.output_types(replies=List[str])
    def run(self, prompt: str):
        return {"replies": [prompt]}


PROMPT_TEMPLATE = """
According to these documents:

{% for doc in documents %}
  {{ doc.content }}
{% endfor %}

Answer the given question: {{question}}
Answer:
"""


def build() -> Pipeline:
    p = Pipeline()
    p.add_component("fetcher", LinkContentFetcher())
    p.add_component("converter", HTMLToDocument())
    p.add_component("splitter", DocumentSplitter())
    p.add_component("ranker", TransformersSimilarityRanker())
    p.add_component("prompt_builder", PromptBuilder(template=PROMPT_TEMPLATE))
    p.add_component("llm", GPTGenerator())

    p.connect("fetcher.streams", "converter.sources")
    p.connect("converter.documents", "splitter.documents")
    p.connect("splitter.documents", "ranker.documents")
    p.connect("ranker.documents", "prompt_builder.question")
    p.connect("prompt_builder.prompt", "llm.prompt")
    return p


pipeline = build()
