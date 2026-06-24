"""ChromaDB adapter used by the RAG pipeline."""

import chromadb


def build_scope_filter(subject_id, document_ids=None):
    return {"subject_id": subject_id}


def rows_from_chroma_result(result):
    rows = []
    ids = result.get("ids", [])
    for i, (doc, meta) in enumerate(zip(result.get("documents", []), result.get("metadatas", []))):
        rows.append({
            "id": ids[i] if i < len(ids) else f"{meta.get('document_id', 'unknown')}_{i}",
            "content": doc,
            "metadata": meta,
            "dense_similarity": 0.0,
            "keyword_score": 0.0,
            "rrf_score": 0.0,
            "rerank_score": 0.0,
        })
    return sorted(rows, key=lambda row: (
        str(row["metadata"].get("document_id", "")),
        int(row["metadata"].get("chunk_index", 0)),
    ))


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
