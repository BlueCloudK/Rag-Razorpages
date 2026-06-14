"""Keyword/BM25-style scoring helpers."""

from collections import Counter


def keyword_score(query_tokens, text_tokens):
    if not query_tokens or not text_tokens:
        return 0.0
    text_counts = Counter(text_tokens)
    hits = sum(text_counts.get(token, 0) for token in query_tokens)
    return hits / max(len(query_tokens), 1)
