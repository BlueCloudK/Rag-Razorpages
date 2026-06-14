"""Structured/adaptive chunking facade."""

from services.document_processor import DocumentProcessor


class StructuredChunker:
    """Small adapter around the current DocumentProcessor chunking pipeline."""

    def __init__(self, chunk_size: int = 850, chunk_overlap: int = 120):
        self.processor = DocumentProcessor(chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    def split_units(self, units):
        return self.processor.split_units(units)

    def process_file(self, file_path: str):
        return self.processor.process_file(file_path)
