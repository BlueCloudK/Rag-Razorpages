"""Optional reranker facade."""


def passthrough_rerank(rows, limit=8):
    return list(rows or [])[:limit]
