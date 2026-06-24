"""Ambiguity guards for short terms and acronym-like questions."""

import re

from utils.text_normalization import is_definition_query, normalize_text


def is_short_ambiguous_term(text):
    value = str(text or "").strip()
    return bool(re.fullmatch(
        r"[A-Za-z0-9]{1,5}(\s+(la gi|nghia la gi|\?))?",
        normalize_text(value),
        re.IGNORECASE,
    ))


def extract_ambiguous_acronym(query):
    raw = str(query or "").strip()
    normalized = normalize_text(raw)
    asks_definition = (
        re.search(r"\b(?:la gi|nghia la gi|viet tat cua gi|what is|what are|meaning of|stands for|means)\b", normalized)
        or re.fullmatch(r"[A-Za-z0-9]{2,5}\??", raw)
    )
    if not asks_definition:
        return ""

    candidates = []
    patterns = [
        r"^\s*([A-Za-z][A-Za-z0-9]{1,4})\s*(?:la)\s*gi\b",
        r"^\s*([A-Za-z][A-Za-z0-9]{1,4})\s*(?:nghia)\s+la\s+gi\b",
        r"^\s*([A-Za-z][A-Za-z0-9]{1,4})\s*(?:viet)\s+tat\s+cua\s+gi\b",
        r"^\s*([A-Za-z][A-Za-z0-9]{1,4})\s*\?$",
        r"\bwhat\s+(?:is|are)\s+([A-Za-z][A-Za-z0-9]{1,4})(?:\s*(?:\?|$)|\s+(?:in|trong|means|stand))",
        r"\b([A-Za-z][A-Za-z0-9]{1,4})\s+(?:means|stands for)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if match:
            candidates.append(match.group(1))

    if not candidates:
        leading_part = re.split(r"\b(?:trong|in)\b", raw, maxsplit=1, flags=re.IGNORECASE)[0]
        first_word = re.match(r"\s*([A-Za-z][A-Za-z0-9]*)\b", leading_part)
        if first_word and len(first_word.group(1)) > 5:
            return ""
        leading_tokens = re.findall(r"\b[A-Za-z][A-Za-z0-9]*\b", leading_part)
        if len(leading_tokens) > 1:
            return ""
        tokens = re.findall(r"\b[A-Za-z][A-Za-z0-9]{1,4}\b", leading_part)
        stop = {"what", "is", "are", "mean", "means", "trong", "file", "pdf"}
        candidates = [token for token in tokens if token.lower() not in stop]

    for candidate in candidates:
        if 2 <= len(candidate) <= 5 and re.fullmatch(r"[A-Za-z][A-Za-z0-9]{1,4}", candidate):
            return candidate.upper()
    return ""


def extract_definition_term(query):
    raw = str(query or "").strip()
    normalized = normalize_text(raw)
    if not is_definition_query(query):
        return ""
    patterns = [
        r"^\s*(.+?)\s+(?:la)\s+gi\b",
        r"^\s*(.+?)\s+(?:nghia)\s+la\s+gi\b",
        r"\bwhat\s+(?:is|are)\s+(.+?)(?:\?|$)",
        r"\bdefine\s+(.+?)(?:\?|$)",
        r"\bmeaning\s+of\s+(.+?)(?:\?|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if not match:
            continue
        term = re.sub(r"\b(?:trong|in)\b.*$", "", match.group(1), flags=re.IGNORECASE).strip(" .?\"'")
        if term:
            return term
    tokens = normalized.split()
    if len(tokens) <= 4:
        return tokens[0] if tokens else ""
    return ""


def has_direct_definition_for_term(term, rows):
    if not term:
        return False
    term_pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", re.IGNORECASE)
    definition_markers = [
        r"\bis\b", r"\bare\b", r"\bmeans\b", r"\bstands\s+for\b", r"\brefers\s+to\b",
        r"\bdefined\s+as\b", r"\bla\b", r"viet\s+tat",
    ]
    marker_pattern = re.compile("|".join(definition_markers), re.IGNORECASE)

    for row in rows:
        meta = row.get("metadata") or {}
        content = str(row.get("content") or "")
        heading_text = " ".join(str(meta.get(key) or "") for key in [
            "heading", "section_path", "detected_title", "chapter_title", "section_title",
        ])
        if term_pattern.search(heading_text) and marker_pattern.search(content[:260]):
            return True

        for match in term_pattern.finditer(content):
            start = max(0, match.start() - 90)
            end = min(len(content), match.end() + 160)
            if marker_pattern.search(content[start:end]):
                return True
    return False
