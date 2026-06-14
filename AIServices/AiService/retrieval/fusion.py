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
