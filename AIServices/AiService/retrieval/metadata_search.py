"""Metadata filtering and retrieval helpers."""


def metadata_candidates(query, rows, normalize_text, tokenize, get_query_chapter_numbers, candidate_pool):
    normalized = normalize_text(query)
    query_chapters = set(get_query_chapter_numbers(query))
    query_terms = set(tokenize(query))
    candidates = []
    for row in rows:
        meta = row.get("metadata", {})
        haystack = normalize_text(
            " ".join([
                str(meta.get("document_name") or ""),
                str(meta.get("chapter_title") or ""),
                str(meta.get("section_path") or meta.get("heading") or ""),
                str(meta.get("source_variant") or ""),
                str(meta.get("source_family") or ""),
            ])
        )
        score = 0.0
        chapter_number = str(meta.get("chapter_number") or "").strip()
        if query_chapters and chapter_number in query_chapters:
            score += 4.0
        if "gomaa" in normalized and "gomaa" in haystack:
            score += 2.0
        if "ddia" in normalized and "ddia" in haystack:
            score += 2.0
        if "modified" in normalized and "modified" in haystack:
            score += 1.5
        if "original" in normalized and "original" in haystack:
            score += 1.5
        score += sum(0.15 for term in query_terms if len(term) > 2 and term in haystack)
        if score <= 0:
            continue
        clone = dict(row)
        clone["metadata_score"] = round(score, 4)
        clone["metadata_rank"] = 0
        candidates.append(clone)
    candidates.sort(key=lambda row: -row.get("metadata_score", 0.0))
    for rank, row in enumerate(candidates):
        row["metadata_rank"] = rank + 1
    return candidates[:candidate_pool]


def metadata_matches(metadata, document_ids=None, chapter_number=None, source_variant=None):
    document_ids = {str(item) for item in (document_ids or []) if str(item).strip()}
    if document_ids and str(metadata.get("document_id", "")) not in document_ids:
        return False
    if chapter_number and int(metadata.get("chapter_number") or 0) != int(chapter_number):
        return False
    if source_variant and str(metadata.get("source_variant") or "") != str(source_variant):
        return False
    return True
