import os
import re
import PyPDF2
from docx import Document as DocxDocument
from pptx import Presentation
from langchain_text_splitters import RecursiveCharacterTextSplitter


class DocumentProcessor:
    def __init__(self, chunk_size=1000, chunk_overlap=200):
        self.chunk_size = int(os.getenv("CHUNK_SIZE", chunk_size))
        self.chunk_overlap = int(os.getenv("CHUNK_OVERLAP", chunk_overlap))
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            length_function=len,
            separators=["\n\n", "\n", ". ", "! ", "? ", "; ", ", ", " ", ""]
        )

    def clean_text(self, text):
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text or "")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        lines = [line.strip() for line in text.split("\n")]
        return "\n".join(lines).strip()

    def detect_heading(self, text):
        line = self.clean_text(text).split("\n")[0][:180]
        if re.match(r"^(chapter|chuong|chÆ°Æ¡ng)\s+\d+", line, re.IGNORECASE):
            return line
        if re.match(r"^\d+(\.\d+)*\s+[A-ZA-ZÄÀÁÂÃÈÉÊÌÍÒÓÔÕÙÚÝÐĂĐĨŨƠƯ]", line):
            return line
        if 8 <= len(line) <= 120 and line.isupper():
            return line.title()
        return ""

    def extract_units_from_pdf(self, file_path):
        units = []
        with open(file_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page_number, page in enumerate(reader.pages, 1):
                text = self.clean_text(page.extract_text() or "")
                if text:
                    units.append({
                        "text": text,
                        "page_number": page_number,
                        "slide_number": None,
                        "heading": self.detect_heading(text)
                    })
        return units

    def extract_units_from_docx(self, file_path):
        doc = DocxDocument(file_path)
        units = []
        current_heading = ""
        current_parts = []

        def flush():
            if current_parts:
                text = self.clean_text("\n".join(current_parts))
                if text:
                    units.append({
                        "text": text,
                        "page_number": None,
                        "slide_number": None,
                        "heading": current_heading or self.detect_heading(text)
                    })

        for para in doc.paragraphs:
            text = self.clean_text(para.text)
            if not text:
                continue
            style_name = (para.style.name if para.style else "").lower()
            looks_like_heading = style_name.startswith("heading") or bool(self.detect_heading(text))
            if looks_like_heading and current_parts:
                flush()
                current_parts = []
            if looks_like_heading:
                current_heading = text[:180]
            current_parts.append(text)

        flush()
        return units

    def extract_units_from_pptx(self, file_path):
        prs = Presentation(file_path)
        units = []
        for slide_number, slide in enumerate(prs.slides, 1):
            slide_text = []
            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text.strip():
                    slide_text.append(shape.text)
            text = self.clean_text("\n".join(slide_text))
            if text:
                units.append({
                    "text": text,
                    "page_number": None,
                    "slide_number": slide_number,
                    "heading": self.detect_heading(text)
                })
        return units

    def split_units(self, units):
        chunks = []
        for unit in units:
            for local_index, chunk_text in enumerate(self.text_splitter.split_text(unit["text"])):
                chunk_text = self.clean_text(chunk_text)
                if len(chunk_text) < 20:
                    continue
                chunks.append({
                    "text": chunk_text,
                    "page_number": unit.get("page_number"),
                    "slide_number": unit.get("slide_number"),
                    "heading": unit.get("heading") or "",
                    "local_index": local_index
                })
        return chunks

    def process_file(self, file_path):
        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".pdf":
            units = self.extract_units_from_pdf(file_path)
        elif ext == ".docx":
            units = self.extract_units_from_docx(file_path)
        elif ext in [".pptx", ".ppt"]:
            units = self.extract_units_from_pptx(file_path)
        else:
            raise ValueError(f"Unsupported file extension: {ext}")

        extracted_chars = sum(len(unit["text"]) for unit in units)
        if extracted_chars < 50:
            print(f"  Warning: Very little text extracted ({extracted_chars} chars)", flush=True)
            return []

        chunks = self.split_units(units)
        print(
            f"  Extracted {extracted_chars} chars -> {len(chunks)} structured chunks "
            f"(size={self.chunk_size}, overlap={self.chunk_overlap})",
            flush=True
        )
        return chunks
