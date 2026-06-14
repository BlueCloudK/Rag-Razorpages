"""File loading facade.

The stable runtime still uses ``services.document_processor.DocumentProcessor``.
This module gives the AI service a production-style ingestion boundary so future
loader changes do not have to touch the FastAPI routes.
"""

from services.document_processor import DocumentProcessor


def load_document_units(file_path: str):
    processor = DocumentProcessor()
    ext = file_path.lower().rsplit(".", 1)[-1]
    if ext == "pdf":
        return processor.extract_units_from_pdf(file_path)
    if ext == "docx":
        return processor.extract_units_from_docx(file_path)
    if ext in {"pptx", "ppt"}:
        return processor.extract_units_from_pptx(file_path)
    raise ValueError(f"Unsupported file extension: .{ext}")
