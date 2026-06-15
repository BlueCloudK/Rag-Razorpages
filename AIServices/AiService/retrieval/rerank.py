"""Optional reranker facade."""


def passthrough_rerank(rows, limit=8):
    return list(rows or [])[:limit]


def rerank_candidates(query, candidates, enable_reranker=False, get_reranker=None, top_k=6):
    if not candidates:
        return []
    if not enable_reranker:
        candidates.sort(key=lambda row: -row["rrf_score"])
        return candidates[:top_k]
    try:
        pairs = [[query, row["content"]] for row in candidates]
        scores = get_reranker().predict(pairs)
        for row, score in zip(candidates, scores):
            row["rerank_score"] = float(score)
        candidates.sort(key=lambda row: -row["rerank_score"])
        return candidates
    except Exception as exc:
        print(f"[RAG] reranker unavailable, using RRF only: {exc}", flush=True)
        candidates.sort(key=lambda row: -row["rrf_score"])
        return candidates
