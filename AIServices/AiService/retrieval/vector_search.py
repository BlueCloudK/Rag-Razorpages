"""Vector search helper facade."""


def vector_search(collection, query_embedding, where=None, n_results=20):
    return collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        where=where,
        include=["documents", "metadatas", "distances"],
    )


def dense_candidates(collection, query_embedding, where=None, n_results=20):
    result = vector_search(collection, query_embedding, where=where, n_results=n_results)
    candidates = []
    docs = result.get("documents", [[]])[0] if result.get("documents") else []
    metas = result.get("metadatas", [[]])[0] if result.get("metadatas") else []
    distances = result.get("distances", [[]])[0] if result.get("distances") else []
    ids = result.get("ids", [[]])[0] if result.get("ids") else []
    for rank, doc in enumerate(docs):
        distance = distances[rank] if rank < len(distances) else 1
        candidates.append({
            "id": ids[rank] if rank < len(ids) else f"dense_{rank}",
            "content": doc,
            "metadata": metas[rank],
            "dense_similarity": round(1 - distance, 4),
            "dense_rank": rank + 1,
            "keyword_rank": None,
            "keyword_score": 0.0,
            "rrf_score": 0.0,
            "rerank_score": 0.0,
        })
    return candidates
