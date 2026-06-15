"""Keyword/BM25-style scoring helpers."""

from collections import Counter
import math


def keyword_score(query_tokens, text_tokens):
    if not query_tokens or not text_tokens:
        return 0.0
    text_counts = Counter(text_tokens)
    hits = sum(text_counts.get(token, 0) for token in query_tokens)
    return hits / max(len(query_tokens), 1)


def keyword_candidates(query, rows, tokenize, candidate_pool):
    query_terms = tokenize(query)
    if not query_terms:
        return []
    docs_tokens = [
        tokenize(f"{row['metadata'].get('document_name', '')} {row['metadata'].get('heading', '')} {row['content']}")
        for row in rows
    ]
    doc_freq = Counter(term for tokens in docs_tokens for term in set(tokens))
    total_docs = max(len(rows), 1)
    scored = []
    for row, tokens in zip(rows, docs_tokens):
        counts = Counter(tokens)
        score = 0.0
        for term in query_terms:
            if counts[term] <= 0:
                continue
            idf = math.log((total_docs - doc_freq[term] + 0.5) / (doc_freq[term] + 0.5) + 1)
            score += counts[term] * idf
        if score > 0:
            clone = dict(row)
            clone["keyword_score"] = round(score, 4)
            scored.append(clone)
    scored.sort(key=lambda row: -row["keyword_score"])
    for rank, row in enumerate(scored):
        row["keyword_rank"] = rank + 1
    return scored[:candidate_pool]
