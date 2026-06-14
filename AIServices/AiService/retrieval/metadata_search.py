"""Metadata filtering helpers."""


def metadata_matches(metadata, document_ids=None, chapter_number=None, source_variant=None):
    document_ids = {str(item) for item in (document_ids or []) if str(item).strip()}
    if document_ids and str(metadata.get("document_id", "")) not in document_ids:
        return False
    if chapter_number and int(metadata.get("chapter_number") or 0) != int(chapter_number):
        return False
    if source_variant and str(metadata.get("source_variant") or "") != str(source_variant):
        return False
    return True
