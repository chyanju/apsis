from typing import List

from haystack import Pipeline, component


@component
class TextCleaner:
    @component.output_types(text=str)
    def run(self, text: str):
        return {"text": text.strip()}


@component
class Embedder:
    @component.output_types(embedding=List[float])
    def run(self, text: str):
        return {"embedding": [0.0]}


@component
class Indexer:
    @component.output_types(ok=bool)
    def run(self, embedding: List[float]):
        return {"ok": True}


@component
class Retriever:
    @component.output_types(docs=List[str])
    def run(self, embedding: List[float]):
        return {"docs": []}


def build():
    shared_cleaner = TextCleaner()
    shared_embedder = Embedder()

    indexing = Pipeline()
    indexing.add_component("cleaner", shared_cleaner)
    indexing.add_component("embedder", shared_embedder)
    indexing.add_component("indexer", Indexer())
    indexing.connect("cleaner.text", "embedder.text")
    indexing.connect("embedder.embedding", "indexer.embedding")

    query = Pipeline()
    query.add_component("cleaner", shared_cleaner)
    query.add_component("embedder", shared_embedder)
    query.add_component("retriever", Retriever())
    query.connect("cleaner.text", "embedder.text")
    query.connect("embedder.embedding", "retriever.embedding")

    return indexing, query


indexing, query = build()
pipeline = indexing
