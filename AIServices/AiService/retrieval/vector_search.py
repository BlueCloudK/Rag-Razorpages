"""Vector search helper facade."""


def vector_search(collection, query_embedding, where=None, n_results=20):
    return collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        where=where,
        include=["documents", "metadatas", "distances"],
    )
