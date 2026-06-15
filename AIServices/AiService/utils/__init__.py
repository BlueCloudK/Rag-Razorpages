"""Shared AI service utilities."""

from .text_normalization import (
    normalize_text,
    compact_preview,
    normalize_for_content_hash,
    compute_content_hash,
    is_vietnamese_query,
    tokenize,
    get_query_chapter_numbers,
    is_definition_query,
    strip_meta_comments,
    clean_llm_output,
)

__all__ = [
    "normalize_text",
    "compact_preview",
    "normalize_for_content_hash",
    "compute_content_hash",
    "is_vietnamese_query",
    "tokenize",
    "get_query_chapter_numbers",
    "is_definition_query",
    "strip_meta_comments",
    "clean_llm_output",
]
