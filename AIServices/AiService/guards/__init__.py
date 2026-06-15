"""Intent, ambiguity, and safety guards."""

from .ambiguity_guard import (
    extract_ambiguous_acronym,
    extract_definition_term,
    has_direct_definition_for_term,
    is_short_ambiguous_term,
)
from .intent_gate import is_likely_document_question
from .safety_guard import classify_intent, is_prompt_injection

looks_like_document_question = is_likely_document_question

__all__ = [
    "classify_intent",
    "extract_ambiguous_acronym",
    "extract_definition_term",
    "has_direct_definition_for_term",
    "is_likely_document_question",
    "is_prompt_injection",
    "is_short_ambiguous_term",
    "looks_like_document_question",
]
