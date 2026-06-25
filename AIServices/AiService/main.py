import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import uvicorn
import os
import shutil
import traceback
import time
import json
import queue
import threading
import asyncio
from uuid import uuid4
from services.rag_service import RagService
from services.document_processor import DocumentProcessor

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
INDEX_PROGRESS = {}


def compact(value, limit=140):
    text = " ".join(str(value or "").split())
    return text[: limit - 1] + "…" if len(text) > limit else text


def log_event(scope, message, **fields):
    details = " ".join(
        f"{key}={compact(value, 110)}"
        for key, value in fields.items()
        if value is not None and value != ""
    )
    print(f"[{scope}] {message}{(' ' + details) if details else ''}", flush=True)


def log_index_summary(document_name, document_id, subject_id, chunks, elapsed):
    first_meta = (chunks[0].get("metadata") or {}) if chunks else {}
    strategies = {}
    zones = {}
    chapters = set()
    for chunk in chunks:
        meta = chunk.get("metadata") or {}
        strategy = meta.get("chunking_strategy") or "unknown"
        zone = meta.get("content_zone") or "body"
        strategies[strategy] = strategies.get(strategy, 0) + 1
        zones[zone] = zones.get(zone, 0) + 1
        chapter = meta.get("chapter_number")
        if chapter:
            chapters.add(str(chapter))
    log_event(
        "INDEX",
        "extract summary",
        document=document_name,
        document_id=document_id,
        subject=subject_id,
        chunks=len(chunks),
        chapters=",".join(sorted(chapters, key=lambda item: int(item) if item.isdigit() else 999)) or "none",
        strategy=first_meta.get("chunking_strategy") or max(strategies, key=strategies.get, default="unknown"),
        zones=", ".join(f"{key}:{value}" for key, value in sorted(zones.items())),
        elapsed=f"{elapsed:.1f}s"
    )


def set_index_progress(document_id, subject_id, document_name, stage, completed=0, total=0, message=""):
    total = int(total or 0)
    completed = max(0, int(completed or 0))
    percent = int((completed * 100) / total) if total > 0 else 0
    INDEX_PROGRESS[str(document_id)] = {
        "document_id": str(document_id),
        "subject_id": int(subject_id),
        "document_name": document_name,
        "stage": stage,
        "completed": completed,
        "total": total,
        "percent": max(0, min(100, percent)),
        "message": message or stage,
        "updated_at": time.time()
    }


def log_chat_trace(turn_id, request, response, elapsed):
    trace = response.get("processing_trace") or {}
    route = {
        "intent": trace.get("intent"),
        "decision": (trace.get("scope") or {}).get("decision") or trace.get("routing_decision"),
        "policy": trace.get("retrieval_policy"),
    }
    query = trace.get("query") or {}
    retrieval = trace.get("retrieval") or {}
    checker = trace.get("checker") or {}
    llm = trace.get("llm") or {}
    citation = trace.get("citation_verification") or {}
    decomposition = query.get("decomposition") or {}
    rounds = retrieval.get("rounds") or []
    branches = retrieval.get("branches") or {}

    log_event(
        "CHAT",
        "route",
        turn=turn_id,
        subject=request.subject_id,
        session=request.session_id,
        docs=len(request.document_ids or []),
        intent=route["intent"],
        decision=route["decision"],
        policy=route["policy"],
        question=compact(request.query, 90)
    )
    if decomposition.get("enabled"):
        log_event(
            "CHAT",
            "decompose",
            turn=turn_id,
            strategy=decomposition.get("strategy"),
            subqueries=" | ".join(decomposition.get("queries") or [])
        )
    if query.get("rewritten") and query.get("rewritten") != query.get("original"):
        log_event("CHAT", "rewrite", turn=turn_id, rewritten=query.get("rewritten"))

    branch_bits = []
    for name in ["vector", "keyword", "metadata"]:
        branch = branches.get(name) or {}
        if branch:
            branch_bits.append(f"{name}:{branch.get('candidate_count', 0)}@{branch.get('duration_ms', 0)}ms")
    log_event(
        "CHAT",
        "retrieval",
        turn=turn_id,
        strategy=retrieval.get("strategy") or response.get("retrieval_strategy"),
        rounds=len(rounds),
        candidates=retrieval.get("candidate_count"),
        selected=retrieval.get("selected_count"),
        branches=", ".join(branch_bits) or "skipped"
    )

    evidence = trace.get("evidence_table") or trace.get("evidence") or response.get("contexts") or []
    used = [item for item in evidence if not isinstance(item, dict) or item.get("used", True) is not False]
    top_sources = []
    for item in used[:5]:
        if not isinstance(item, dict):
            continue
        source = item.get("source")
        page = item.get("page_number") or item.get("page")
        chapter = item.get("chapter_number") or item.get("chapter")
        score = item.get("final_score") or item.get("similarity")
        top_sources.append(f"{source}:c{chapter}/p{page}/s{score}")
    log_event(
        "CHAT",
        "evidence",
        turn=turn_id,
        used=len(used),
        confidence=checker.get("confidence") or response.get("confidence"),
        sufficient=checker.get("sufficient"),
        top=" | ".join(top_sources)
    )
    log_event(
        "CHAT",
        "citations",
        turn=turn_id,
        status=citation.get("status"),
        verified=" | ".join(citation.get("verified_sources") or response.get("sources") or []),
        rejected=" | ".join(citation.get("rejected_sources") or [])
    )
    log_event(
        "CHAT",
        "done",
        turn=turn_id,
        model=llm.get("model") or response.get("model"),
        fallback=llm.get("fallback_used") or response.get("fallback_used"),
        answer_chars=len(str(response.get("answer") or "")),
        elapsed=f"{elapsed:.1f}s"
    )


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

        start = time.time()
        file_size = os.path.getsize(temp_file_path) if os.path.exists(temp_file_path) else 0
        log_event("UPLOAD", "received", filename=file.filename, subject=subject_id, size=f"{file_size / 1024 / 1024:.2f}MB")
        chunks = document_processor.process_file(temp_file_path)
        log_index_summary(file.filename, file.filename, subject_id, chunks, time.time() - start)

        if len(chunks) == 0:
            return {"status": "error", "message": "No text extracted", "indexed": False}

        embed_start = time.time()
        rag_service.embed_and_store(chunks, subject_id, file.filename, file.filename)
        log_event("UPLOAD", "indexed", filename=file.filename, chunks=len(chunks), elapsed=f"{time.time() - embed_start:.1f}s")

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
    turn_id = uuid4().hex[:8]
    start = time.time()
    log_event(
        "CHAT",
        "start",
        turn=turn_id,
        subject=request.subject_id,
        session=request.session_id,
        docs=len(request.document_ids or []),
        history=len(request.history or []),
        memory_chars=len(request.subject_memory or ""),
        question=compact(request.query, 110)
    )
    response = rag_service.generate_answer(
        request.query,
        request.subject_id,
        document_ids=request.document_ids,
        history=request.history,
        subject_memory=request.subject_memory
    )
    if isinstance(response, dict):
        log_chat_trace(turn_id, request, response, time.time() - start)
    return response


@app.post("/api/chat/ask-stream")
async def ask_question_stream(request: ChatRequest):
    """Stream coarse but real RAG pipeline events while one chat request is processed."""
    turn_id = uuid4().hex[:8]
    start = time.time()
    events = queue.Queue()

    def put_event(event_type, payload):
        events.put({
            "type": event_type,
            "payload": payload or {}
        })

    def worker():
        try:
            log_event(
                "CHAT",
                "stream_start",
                turn=turn_id,
                subject=request.subject_id,
                session=request.session_id,
                docs=len(request.document_ids or []),
                question=compact(request.query, 110)
            )
            response = rag_service.generate_answer(
                request.query,
                request.subject_id,
                document_ids=request.document_ids,
                history=request.history,
                subject_memory=request.subject_memory,
                trace_callback=put_event
            )
            if isinstance(response, dict):
                log_chat_trace(turn_id, request, response, time.time() - start)
            put_event("final", response)
        except Exception as exc:
            traceback.print_exc()
            put_event("error", {
                "message": str(exc),
                "answer": "AI Engine returned an error while streaming the trace.",
                "sources": [],
                "contexts": [],
                "confidence": 0,
                "fallback_used": True
            })
        finally:
            events.put(None)

    def event_generator():
        threading.Thread(target=worker, daemon=True).start()
        while True:
            item = events.get()
            if item is None:
                break
            event_type = item.get("type") or "trace"
            payload = item.get("payload") or {}
            yield f"event: {event_type}\n"
            yield "data: " + json.dumps(payload, ensure_ascii=False, default=str) + "\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


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
        set_index_progress(document_id, subject_id, document_name, "upload_received", 0, 0, "Upload received by AI Service")
        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        return await asyncio.to_thread(
            index_existing_document_from_path,
            subject_id,
            document_id,
            document_name,
            temp_file_path
        )
    except Exception as e:
        print(f"[INDEX ERROR] {document_name}: {e}")
        traceback.print_exc()
        set_index_progress(document_id, subject_id, document_name, "failed", 0, 0, str(e))
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        return {"status": "error", "message": str(e), "indexed": False}


def index_existing_document_from_path(subject_id: int, document_id: str, document_name: str, temp_file_path: str):
    """Run the blocking extract/embed/store pipeline outside FastAPI's event loop."""
    try:
        start = time.time()
        file_size = os.path.getsize(temp_file_path) if os.path.exists(temp_file_path) else 0
        log_event(
            "INDEX",
            "received",
            document=document_name,
            document_id=document_id,
            subject=subject_id,
            size=f"{file_size / 1024 / 1024:.2f}MB"
        )
        set_index_progress(document_id, subject_id, document_name, "extracting", 0, 0, "Extracting text and preparing chunks")
        chunks = document_processor.process_file(temp_file_path)
        set_index_progress(document_id, subject_id, document_name, "chunked", len(chunks), len(chunks), f"Extracted {len(chunks)} chunks")
        log_index_summary(document_name, document_id, subject_id, chunks, time.time() - start)

        if len(chunks) == 0:
            set_index_progress(document_id, subject_id, document_name, "failed", 0, 0, "No text extracted")
            return {"status": "error", "message": "No text extracted", "indexed": False}

        embed_start = time.time()
        indexed_count = rag_service.embed_and_store(
            chunks,
            subject_id,
            document_name,
            document_id,
            progress_callback=lambda stage, completed, total, message: set_index_progress(
                document_id,
                subject_id,
                document_name,
                stage,
                completed,
                total,
                message
            )
        )
        log_event("INDEX", "stored", document=document_name, document_id=document_id, chunks=indexed_count, elapsed=f"{time.time() - embed_start:.1f}s")

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
        set_index_progress(document_id, subject_id, document_name, "failed", 0, 0, str(e))
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        return {"status": "error", "message": str(e), "indexed": False}


@app.get("/api/documents/{document_id}/index-progress")
async def get_document_index_progress(document_id: str):
    progress = INDEX_PROGRESS.get(str(document_id))
    if not progress:
        return {
            "document_id": str(document_id),
            "stage": "unknown",
            "completed": 0,
            "total": 0,
            "percent": 0,
            "message": "No active runtime progress for this document.",
            "active": False
        }
    active = progress.get("stage") not in {"indexed", "failed"}
    return {**progress, "active": active}


@app.delete("/api/documents/{document_id}")
async def delete_indexed_document(document_id: str):
    try:
        deleted = rag_service.delete_document(document_id)
        INDEX_PROGRESS.pop(str(document_id), None)
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
