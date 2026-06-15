"""Candidate fusion helpers."""


def reciprocal_rank_fusion(rank_lists, k=60):
    scores = {}
    rows = {}
    for ranked in rank_lists:
        for rank, row in enumerate(ranked, start=1):
            row_id = row.get("id") or row.get("chunk_id") or f"row:{len(rows)}"
            scores[row_id] = scores.get(row_id, 0.0) + 1.0 / (k + rank)
            rows[row_id] = row
    return [
        {**rows[row_id], "rrf_score": score}
        for row_id, score in sorted(scores.items(), key=lambda item: item[1], reverse=True)
    ]


def fuse_dense_keyword_metadata(dense_rows, keyword_rows, metadata_rows=None, candidate_pool=20):
    fused = {}
    for source_rows, rank_key in [
        (dense_rows, "dense_rank"),
        (keyword_rows, "keyword_rank"),
        (metadata_rows or [], "metadata_rank"),
    ]:
        for index, row in enumerate(source_rows):
            item = fused.setdefault(row["id"], dict(row))
            rank = row.get(rank_key) or index + 1
            item["rrf_score"] = item.get("rrf_score", 0.0) + 1.0 / (60 + rank)
            item["dense_similarity"] = max(item.get("dense_similarity", 0.0), row.get("dense_similarity", 0.0))
            item["keyword_score"] = max(item.get("keyword_score", 0.0), row.get("keyword_score", 0.0))
            item["metadata_score"] = max(item.get("metadata_score", 0.0), row.get("metadata_score", 0.0))
    rows = list(fused.values())
    rows.sort(key=lambda row: -row["rrf_score"])
    return rows[:candidate_pool]


def merge_ranked_rows(ranked_groups, candidate_pool=20):
    merged = {}
    for group_index, rows in enumerate(ranked_groups):
        for rank, row in enumerate(rows):
            item = merged.setdefault(row["id"], dict(row))
            bonus = 1.0 / (40 + rank + group_index + 1)
            item["rrf_score"] = max(item.get("rrf_score", 0.0), row.get("rrf_score", 0.0)) + bonus
            item["dense_similarity"] = max(item.get("dense_similarity", 0.0), row.get("dense_similarity", 0.0))
            item["keyword_score"] = max(item.get("keyword_score", 0.0), row.get("keyword_score", 0.0))
            item["rerank_score"] = max(item.get("rerank_score", 0.0), row.get("rerank_score", 0.0))
    result = list(merged.values())
    result.sort(key=lambda row: (
        -row.get("rerank_score", 0.0),
        -row.get("rrf_score", 0.0),
        -row.get("dense_similarity", 0.0),
    ))
    return result[:candidate_pool]
