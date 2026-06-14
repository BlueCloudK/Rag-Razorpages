"""Ambiguous short-term guard."""

import re


def is_short_ambiguous_term(text: str) -> bool:
    value = str(text or "").strip()
    return bool(re.fullmatch(r"[A-Za-zĐđ]{1,5}(\s+(là gì|la gi|nghĩa là gì|nghia la gi|\?))?", value, re.IGNORECASE))
