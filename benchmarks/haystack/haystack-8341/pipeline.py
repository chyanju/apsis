from typing import List

from haystack import Document, Pipeline, component
from haystack.core.component.types import Variadic


@component
class ConditionalDocumentCreator:
    def __init__(self, content: str):
        self.content = content

    @component.output_types(documents=List[Document], noop=type(None))
    def run(self, create_document: bool = False):
        if create_document:
            return {"documents": [Document(id=self.content, content=self.content)]}
        return {"noop": None}


@component
class DocumentJoiner:
    @component.output_types(documents=List[Document])
    def run(self, documents: Variadic[List[Document]]):
        merged: List[Document] = []
        for docs in documents:
            merged.extend(docs)
        return {"documents": merged}


def build() -> Pipeline:
    p = Pipeline()
    p.add_component("first_creator", ConditionalDocumentCreator(content="First document"))
    p.add_component("second_creator", ConditionalDocumentCreator(content="Second document"))
    p.add_component("third_creator", ConditionalDocumentCreator(content="Third document"))
    p.add_component("joiner", DocumentJoiner())
    p.connect("first_creator.documents", "joiner.documents")
    p.connect("second_creator.documents", "joiner.documents")
    p.connect("third_creator.documents", "joiner.documents")
    return p


pipeline = build()
