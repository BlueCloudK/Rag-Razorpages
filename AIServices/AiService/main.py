import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn
import os
import shutil
import traceback
from services.document_processor import DocumentProcessor
from services.rag_service import RagService

app = FastAPI(title="EduChatbot AI Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

rag_service = RagService()
document_processor = DocumentProcessor()


class ChatRequest(BaseModel):
    session_id: int
    subject_id: int
    query: str
    document_ids: list[str] = Field(default_factory=list)
    history: list[dict[str, str]] = Field(default_factory=list)
    subject_memory: str = ""


@app.get("/")
def read_root():
    return {"message": "AI Service is running"}


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "provider": rag_service.get_llm_provider(),
        "model": rag_service.get_llm_model_name(),
        "retrieval_strategy": "hybrid_rerank"
    }


@app.post("/api/documents/upload")
async def upload_and_index_document(subject_id: int = Form(...), file: UploadFile = File(...)):
    """Upload and index document synchronously."""
    temp_dir = "temp_uploads"
    os.makedirs(temp_dir, exist_ok=True)
    temp_file_path = os.path.join(temp_dir, file.filename)

    try:
        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        print(f"[UPLOAD] Processing: {file.filename} for subject_id={subject_id}")
        chunks = document_processor.process_file(temp_file_path)
        print(f"[UPLOAD] Extracted {len(chunks)} chunks")

        if len(chunks) == 0:
            return {"status": "error", "message": "No text extracted", "indexed": False}

        rag_service.embed_and_store(chunks, subject_id, file.filename, file.filename)
        print(f"[UPLOAD] Indexed {len(chunks)} chunks for: {file.filename}")

        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)

        return {"status": "success", "filename": file.filename, "chunks": len(chunks), "indexed": True}
    except Exception as e:
        print(f"[UPLOAD ERROR] {file.filename}: {e}")
        traceback.print_exc()
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        return {"status": "error", "message": str(e), "indexed": False}


@app.post("/api/chat/ask")
async def ask_question(request: ChatRequest):
    return rag_service.generate_answer(
        request.query,
        request.subject_id,
        document_ids=request.document_ids,
        history=request.history,
        subject_memory=request.subject_memory
    )


@app.post("/api/documents/index")
async def index_existing_document(
    subject_id: int = Form(...),
    document_id: str = Form(...),
    document_name: str = Form(...),
    file: UploadFile = File(...)
):
    """Upload and index a document with a stable caller-provided document id."""
    temp_dir = "temp_uploads"
    os.makedirs(temp_dir, exist_ok=True)
    temp_file_path = os.path.join(temp_dir, file.filename)

    try:
        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        print(f"[INDEX] Processing: {document_name} ({document_id}) for subject_id={subject_id}")
        chunks = document_processor.process_file(temp_file_path)

        if len(chunks) == 0:
            return {"status": "error", "message": "No text extracted", "indexed": False}

        indexed_count = rag_service.embed_and_store(chunks, subject_id, document_name, document_id)
        print(f"[INDEX] Indexed {indexed_count} chunks for: {document_name}")

        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)

        return {
            "status": "success",
            "filename": document_name,
            "document_id": document_id,
            "chunks": indexed_count,
            "indexed": indexed_count > 0
        }
    except Exception as e:
        print(f"[INDEX ERROR] {document_name}: {e}")
        traceback.print_exc()
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        return {"status": "error", "message": str(e), "indexed": False}


@app.delete("/api/documents/{document_id}")
async def delete_indexed_document(document_id: str):
    try:
        deleted = rag_service.delete_document(document_id)
        return {"status": "success", "document_id": document_id, "deleted_chunks": deleted}
    except Exception as e:
        traceback.print_exc()
        return {"status": "error", "message": str(e), "deleted_chunks": 0}


@app.get("/api/documents/{document_id}/chunks")
async def inspect_indexed_document_chunks(document_id: str, offset: int = 0, limit: int = 8):
    try:
        return rag_service.inspect_document_chunks(document_id, offset=offset, limit=limit)
    except Exception as e:
        traceback.print_exc()
        return {"document_id": document_id, "total": 0, "offset": offset, "limit": limit, "chunks": [], "error": str(e)}


@app.get("/api/subjects/{subject_id}/chunks")
async def inspect_indexed_subject_chunks(subject_id: int, offset: int = 0, limit: int = 8):
    try:
        return rag_service.inspect_subject_chunks(subject_id, offset=offset, limit=limit)
    except Exception as e:
        traceback.print_exc()
        return {"document_id": f"subject:{subject_id}", "total": 0, "offset": offset, "limit": limit, "chunks": [], "error": str(e)}


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
