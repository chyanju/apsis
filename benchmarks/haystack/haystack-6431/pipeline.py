from typing import List

from haystack import Pipeline, component
from haystack.dataclasses import Document


@component
class Cleaner:
    @component.output_types(documents=List[Document])
    def run(self, documents: List[Document]):
        return {"documents": documents}


@component
class Splitter:
    @component.output_types(documents=List[Document])
    def run(self, documents: List[Document]):
        return {"documents": documents}


@component
class Writer:
    @component.output_types(written=int)
    def run(self, documents: List[Document]):
        return {"written": len(documents)}


@component
class Scorer:
    @component.output_types(score=float)
    def run(self, documents: List[Document]):
        return {"score": float(len(documents))}


shared_cleaner = Cleaner()


def build_indexing() -> Pipeline:
    p = Pipeline()
    p.add_component("cleaner", shared_cleaner)
    p.add_component("splitter", Splitter())
    p.add_component("writer", Writer())
    p.connect("cleaner.documents", "splitter.documents")
    p.connect("splitter.documents", "writer.documents")
    return p


def build_evaluation() -> Pipeline:
    p = Pipeline()
    p.add_component("cleaner", shared_cleaner)
    p.add_component("scorer", Scorer())
    p.connect("cleaner.documents", "scorer.documents")
    return p


indexing_pipeline = build_indexing()
evaluation_pipeline = build_evaluation()

pipeline = indexing_pipeline
