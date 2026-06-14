"""ChromaDB adapter used by the RAG pipeline."""

import chromadb


class ChromaStore:
    def __init__(self, path: str, collection_name: str = "edu_documents"):
        self.client = chromadb.PersistentClient(path=path)
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def add(self, documents, embeddings, metadatas, ids):
        return self.collection.add(
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
            ids=ids,
        )

    def get(self, **kwargs):
        return self.collection.get(**kwargs)

    def query(self, **kwargs):
        return self.collection.query(**kwargs)

    def delete(self, **kwargs):
        return self.collection.delete(**kwargs)
