"""Text normalization helpers shared by RAG modules."""

import re
import unicodedata


def normalize_text(value: str) -> str:
    text = str(value or "").lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = re.sub(r"\.(pdf|docx|pptx|ppt)\b", " ", text)
    text = re.sub(r"[_\-]+", " ", text)
    text = re.sub(r"[^a-z0-9\s]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def compact_preview(value: str, limit: int = 180) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[: limit - 1] + "…" if len(text) > limit else text
