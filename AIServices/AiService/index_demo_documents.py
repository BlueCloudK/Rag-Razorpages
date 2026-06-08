import argparse
import os
import shutil
import sys
from pathlib import Path

from services.rag_service import RagService
from services.document_processor import DocumentProcessor


SERVICE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = SERVICE_ROOT.parents[1]
SAMPLE_DIR = REPO_ROOT / "sample-documents"
SAMPLE_DOCS = [
    ("demo-gomaa", "sample-gomaa-software-modeling-ch1-ch2.pdf", "gomaa-software-modeling", "original"),
    (
        "demo-gomaa-duplicate",
        "sample-gomaa-software-modeling-ch1-ch2.pdf",
        "sample-gomaa-software-modeling-ch1-ch2-duplicate.pdf",
        "gomaa-software-modeling",
        "original",
    ),
    (
        "demo-gomaa-same-name",
        "sample-gomaa-software-modeling-ch1-ch2.pdf",
        "sample-gomaa-software-modeling-ch1-ch2.pdf",
        "gomaa-software-modeling",
        "original",
    ),
    ("demo-gomaa-modified-wrong", "sample-gomaa-software-modeling-ch1-ch2-modified-wrong.pdf", "gomaa-software-modeling", "modified"),
    ("demo-ddia", "sample-ddia-ch1-ch2.pdf", "ddia", "original"),
]


def reset_chroma_if_requested(reset):
    if not reset:
        return
    chroma_path = Path(os.getenv("CHROMA_DB_PATH") or (SERVICE_ROOT / "chroma_db")).resolve()
    if chroma_path.exists():
        print(f"Deleting ChromaDB dev data: {chroma_path}", flush=True)
        shutil.rmtree(chroma_path)


def main():
    parser = argparse.ArgumentParser(description="Index the shortened demo PDFs into ChromaDB.")
    parser.add_argument("--subject-id", type=int, default=int(os.getenv("DEMO_SUBJECT_ID", "1")))
    parser.add_argument("--reset", action="store_true", help="Delete current AiService/chroma_db before indexing.")
    args = parser.parse_args()

    reset_chroma_if_requested(args.reset)
    processor = DocumentProcessor()
    rag = RagService()

    for item in SAMPLE_DOCS:
        if len(item) == 4:
            document_id, source_filename, document_name, source_family, source_variant = (
                item[0],
                item[1],
                item[1],
                item[2],
                item[3],
            )
        else:
            document_id, source_filename, document_name, source_family, source_variant = item
        path = SAMPLE_DIR / source_filename
        if not path.exists():
            raise FileNotFoundError(path)
        print(f"Indexing {document_name} for subject_id={args.subject_id}", flush=True)
        chunks = processor.process_file(str(path))
        for chunk in chunks:
            chunk["source_family"] = source_family
            chunk["source_variant"] = source_variant
        count = rag.embed_and_store(
            chunks,
            subject_id=args.subject_id,
            document_name=document_name,
            document_id=document_id,
        )
        print(f"Stored {count} chunks for {document_name}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
