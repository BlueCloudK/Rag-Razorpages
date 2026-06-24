"""Text normalization helpers shared by RAG modules.

All functions are pure (no side effects, no imports from services/).
"""

import hashlib
import re
import unicodedata


def normalize_text(value):
    """Normalize text for matching: lowercase, strip accents, remove punctuation."""
    text = str(value or "").lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = re.sub(r"\.(pdf|docx|pptx|ppt)\b", " ", text)
    text = re.sub(r"[_\-]+", " ", text)
    text = re.sub(r"[^a-z0-9\s]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def compact_preview(value, limit=180):
    """Truncate text for display previews."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[: limit - 1] + "\u2026" if len(text) > limit else text


def normalize_for_content_hash(value):
    """NFKC-normalize, lowercase, and collapse whitespace for content hashing."""
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    text = re.sub(r"\s+", " ", text).strip()
    return text


def compute_content_hash(value):
    """SHA-256 hash of normalized content for duplicate detection."""
    normalized = normalize_for_content_hash(value)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else ""


def is_vietnamese_query(query):
    """Detect whether a query is in Vietnamese (accented chars or common terms)."""
    raw = str(query or "").lower()
    if re.search(
        r"[\u0103\u00e2\u0111\u00ea\u00f4\u01a1\u01b0"
        r"\u00e1\u00e0\u1ea3\u00e3\u1ea1\u1ea5\u1ea7\u1ea9\u1eab\u1ead"
        r"\u1eaf\u1eb1\u1eb3\u1eb5\u1eb7"
        r"\u00e9\u00e8\u1ebb\u1ebd\u1eb9\u1ebf\u1ec1\u1ec3\u1ec5\u1ec7"
        r"\u00ed\u00ec\u1ec9\u0129\u1ecb"
        r"\u00f3\u00f2\u1ecf\u00f5\u1ecd\u1ed1\u1ed3\u1ed5\u1ed7\u1ed9"
        r"\u1edb\u1edd\u1edf\u1ee1\u1ee3"
        r"\u00fa\u00f9\u1ee7\u0169\u1ee5\u1ee9\u1eeb\u1eed\u1eef\u1ef1"
        r"\u00fd\u1ef3\u1ef7\u1ef9\u1ef5]",
        raw,
    ):
        return True
    normalized = normalize_text(raw)
    return any(
        term in normalized
        for term in [
            "chuong", "tai lieu", "tom tat", "y chinh", "noi ve", "liet ke",
            "co may", "bao nhieu", "phan nao", "muc nao", "sach", "nguon",
        ]
    )


def tokenize(value):
    """Tokenize text into search terms, stripping stopwords."""
    stopwords = {
        "la", "gi", "co", "cua", "cac", "nhung", "mot", "nay", "kia",
        "trong", "ve", "cho", "toi", "minh", "hay", "neu", "thi", "va",
        "the", "nao", "duoc", "khong", "file", "pdf", "tai", "lieu",
        "mon", "chuong", "chapter", "please", "what", "how", "many",
    }
    return [
        term
        for term in normalize_text(value).split()
        if len(term) >= 3 and term not in stopwords
    ]


def get_query_chapter_numbers(query):
    """Extract chapter numbers mentioned in a query."""
    normalized = normalize_text(query)
    numbers = []
    for match in re.finditer(r"\b(?:chapter|chuong+)\s*([0-9]{1,2})\b", normalized):
        value = int(match.group(1))
        if 1 <= value <= 40 and value not in numbers:
            numbers.append(value)
    return numbers


def is_definition_query(query):
    """Check whether query is asking for a definition."""
    normalized = normalize_text(query)
    return bool(
        re.search(
            r"\b(?:la gi|nghia la gi|viet tat cua gi|what is|what are"
            r"|meaning of|stands for|means|define|definition)\b",
            normalized,
        )
    )


def strip_meta_comments(text):
    """Remove LLM meta-commentary like 'Note:', 'Let me know', etc."""
    lines = str(text or "").splitlines()
    cleaned = []
    meta_patterns = [
        r"^\s*\*{0,2}note\s*\*{0,2}\s*:",
        r"^\s*ghi ch\u00fa\s*:",
        r"^\s*i['\u2019]?ve aimed\b",
        r"^\s*let me know\b",
        r"^\s*h\u00e3y cho t\u00f4i bi\u1ebft\b",
        r"^\s*n\u1ebfu b\u1ea1n mu\u1ed1n\b",
        r"^\s*i hope this helps\b",
        r"^\s*as an ai\b",
        r"^\s*[-*]\s*\*{0,2}\s*inferred note\s*\*{0,2}\s*:",
        r"^\s*[-*]\s*\*{0,2}\s*nh\u1eadn x\u00e9t suy ra\s*\*{0,2}\s*:",
        r"^\s*\*{0,2}inferred note\s*\*{0,2}\s*:",
        r"^\s*\*{0,2}nh\u1eadn x\u00e9t suy ra\s*\*{0,2}\s*:",
        r"^\s*okay,\s*let['\u2019]?s\s+analy[sz]e\b",
        r"^\s*let['\u2019]?s\s+analy[sz]e\b",
        r"^\s*question\s*:",
        r"^\s*answer\s*:",
    ]
    for line in lines:
        if any(re.search(pattern, line, flags=re.IGNORECASE) for pattern in meta_patterns):
            continue
        cleaned.append(line)
    text = "\n".join(cleaned).strip()
    text = re.sub(r"\n-{3,}\s*$", "", text).strip()
    text = re.sub(r"\(\s*This is inferred[^)]*\)", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"\bUncertainty exists regarding[^.]*\.", "", text, flags=re.IGNORECASE).strip()
    return text


def clean_llm_output(text):
    """Strip <think> blocks and meta-commentary from LLM output."""
    text = str(text or "").strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = strip_meta_comments(text)
    return text.strip()
