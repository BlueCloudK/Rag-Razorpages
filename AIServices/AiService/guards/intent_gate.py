"""Document-intent and query-shape helpers for RAG routing."""

import re

from utils.text_normalization import get_query_chapter_numbers, normalize_text


def is_short_followup_query(query):
    normalized = normalize_text(query).strip()
    followup_terms = [
        "liet ke ra", "liet ke ra di", "noi tiep", "giai thich them",
        "giai thich ky hon", "noi ky hon", "noi ki hon", "ro hon", "chi tiet hon",
        "so voi chuong 1", "so voi chuong 2",
        "list them", "continue", "explain more", "more detail", "compare with chapter",
    ]
    return len(normalized.split()) <= 6 and any(
        term == normalized or normalized.startswith(term) for term in followup_terms
    )


def is_likely_document_question(query, history=None):
    normalized = normalize_text(query)
    tokens = normalized.split()
    if not normalized:
        return False

    document_terms = [
        "tai lieu", "file", "pdf", "sach", "book", "document", "source", "nguon",
        "chuong", "chapter", "section", "muc", "phan", "trang", "page",
        "gomaa", "ddia", "uml", "comet", "data model", "database", "normalization",
        "use case", "class diagram", "reliability", "scalability", "maintainability",
        "software modeling", "design", "object oriented",
    ]
    learning_terms = [
        "tom tat", "summary", "summarize", "y chinh", "main idea", "noi dung",
        "noi ve", "noi gi", "giai thich", "explain", "so sanh", "compare",
        "liet ke", "list", "cac phan", "khac nhau", "giong nhau", "mau thuan",
        "definition", "define", "nghia la gi", "la gi", "what is", "how many",
    ]
    if any(term in normalized for term in document_terms):
        return True
    if any(term in normalized for term in learning_terms):
        return True
    if history and is_short_followup_query(query):
        return True
    if "?" in str(query or "") and len(tokens) >= 4:
        personal_terms = {"toi", "tao", "minh", "ban", "dep", "xau", "buon", "vui", "yeu", "ghet"}
        if not any(term in tokens for term in personal_terms):
            return True
    return False


def is_clear_out_of_scope_query(normalized):
    out_of_scope_terms = [
        "hom nay thu may", "ngay may", "may gio", "thoi tiet", "weather",
        "tin tuc", "news", "gia vang", "gia bitcoin", "ti gia",
        "mua laptop", "nen mua", "tu van mua", "shopping",
        "viet code", "lap trinh giup", "fix code", "debug code",
        "chien tranh", "lich su the gioi", "bong da", "the thao",
        "nau an", "cong thuc nau", "du lich", "dat ve",
        "kubernetes",
    ]
    return any(term in normalized for term in out_of_scope_terms)


def is_outline_query(query):
    normalized = normalize_text(query)
    return any(term in normalized for term in [
        "cac chuong", "danh sach chuong", "liet ke chuong", "muc luc",
        "co may chuong", "bao nhieu chuong", "so chuong", "nhung chuong", "chuong nao",
        "chapters", "chapter list", "number of chapter", "table of contents",
    ])


def is_section_query(query):
    normalized = normalize_text(query)
    return any(term in normalized for term in [
        "cac phan", "phan nao", "cac muc", "muc nao", "section", "subsection",
        "liet ke ra", "liet ke cac phan", "list sections", "main sections",
    ])


def is_summary_query(query):
    normalized = normalize_text(query)
    return any(term in normalized for term in [
        "noi ve gi", "tom tat", "y chinh", "main idea", "summary",
        "summarize", "explain", "giai thich", "noi dung",
    ])


def is_document_summary_query(query):
    normalized = normalize_text(query)
    if get_query_chapter_numbers(query):
        return False
    if is_outline_query(query) or is_section_query(query):
        return False
    summary_terms = [
        "tom tat tai lieu", "tom tat cac y chinh", "cac y chinh cua tai lieu",
        "y chinh cua tai lieu", "noi dung chinh cua tai lieu", "document summary",
        "summary of this document", "main ideas in this document",
        "main ideas of this document", "summarize the main ideas",
        "file gomaa hien co noi dung gi", "file ddia hien co noi dung gi",
        "file nay hien co noi dung gi", "file nay co noi dung gi",
        "file gomaa co noi dung gi", "file ddia co noi dung gi",
    ]
    return any(term in normalized for term in summary_terms)


def is_conflict_sensitive_query(query):
    normalized = normalize_text(query)
    if any(term in normalized for term in ["so voi chuong", "compare with chapter"]):
        return False
    return any(term in normalized for term in [
        "khac nhau", "mau thuan", "conflict", "different", "compare",
        "use case", "class diagram", "database normalization", "normalization",
        "nguon nao", "noi ve",
    ])


def is_duplicate_sensitive_query(query):
    normalized = normalize_text(query)
    return any(term in normalized for term in [
        "trung", "trung lap", "giong nhau", "ban giong nhau",
        "duplicate", "same content", "same document",
    ])


def should_rewrite_query(query, history):
    normalized = normalize_text(query)
    return bool(history) and (
        is_short_followup_query(query)
        or len(normalized.split()) <= 7
        or bool(re.search(r"\b(?:it|that|this|do|there|cai do|phan do|chuong do)\b", normalized))
    )
