"""Lightweight document-intent gate."""

DOCUMENT_TERMS = {
    "chapter", "chương", "chuong", "section", "mục", "muc", "summary", "tóm tắt", "tom tat",
    "document", "tài liệu", "tai lieu", "book", "sách", "sach", "uml", "data model", "database",
}


def looks_like_document_question(text: str) -> bool:
    normalized = str(text or "").lower()
    return any(term in normalized for term in DOCUMENT_TERMS)
