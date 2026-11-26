from typing import List

from haystack import Pipeline, component


@component
class Retriever:
    @component.output_types(documents=List[str])
    def run(self, query: str):
        return {"documents": ["doc1", "doc2", "doc3"]}


@component
class QAPromptNode:
    @component.output_types(prompt=str)
    def run(self, documents: str):
        return {"prompt": documents}


def build() -> Pipeline:
    p = Pipeline()
    p.add_component("retriever", Retriever())
    p.add_component("qa_prompt_node", QAPromptNode())
    p.connect("retriever.documents", "qa_prompt_node.documents")
    return p


pipeline = build()
