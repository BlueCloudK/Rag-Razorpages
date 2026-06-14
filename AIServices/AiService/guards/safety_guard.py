"""Prompt-injection guard helpers."""

INJECTION_TERMS = [
    "ignore previous",
    "ignore sources",
    "bỏ qua tài liệu",
    "bo qua tai lieu",
    "system prompt",
    "hidden prompt",
    "answer from your own knowledge",
]


def is_prompt_injection(text: str) -> bool:
    normalized = str(text or "").lower()
    return any(term in normalized for term in INJECTION_TERMS)
