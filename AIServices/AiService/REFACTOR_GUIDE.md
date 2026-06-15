# AI Service Refactor Guide

This note documents the current Python AI Service structure after the module refactor. It is intentionally written in ASCII English to avoid Windows encoding issues.

## Current Goal

The AI Service is still centered on `services/rag_service.py`, but large groups of reusable logic have been moved into focused modules. `RagService` should now act more like an orchestrator:

- route the request;
- call guards;
- retrieve evidence;
- assemble trace data;
- call the local LLM;
- return the existing API response contract.

The public FastAPI endpoints and response fields were not changed.

## Runtime Entry Points

- `main.py`
- `services/rag_service.py`
- `services/document_processor.py`

Keep these stable unless a change is tested with compile, build, and benchmark.

## Modules Now Used By Runtime

### `utils/`

`utils/text_normalization.py` contains pure helpers:

- text normalization;
- tokenization;
- Vietnamese query detection;
- content hash helpers;
- LLM output cleanup.

### `guards/`

Guard logic is now outside `rag_service.py`:

- `intent_gate.py`: document intent, outline/summary/follow-up query shape.
- `ambiguity_guard.py`: short acronym/term guards such as WC, ER, CPU.
- `safety_guard.py`: prompt injection, small talk, creative/out-of-scope, exam-answer requests.

`RagService` keeps wrapper methods for backward compatibility.

### `llm/`

`llm/ollama_client.py` owns:

- Ollama `/api/generate` calls;
- Qwen `/no_think` prompt preparation;
- JSON parsing for small planner/checker calls.

### `embeddings/`

`embeddings/embedder.py` owns:

- HuggingFace embedding model loading;
- query embedding cache;
- document/query embedding calls.

### `vectordb/`

`vectordb/chroma_store.py` owns:

- Chroma scope filter creation;
- Chroma result to row conversion;
- basic Chroma adapter wrapper.

### `retrieval/`

Retrieval helpers are now split by responsibility:

- `vector_search.py`: Chroma vector candidates.
- `keyword_search.py`: BM25-style keyword candidates.
- `metadata_search.py`: chapter/document/source metadata candidates.
- `fusion.py`: RRF merge and multi-round merge.
- `rerank.py`: optional reranker with RRF fallback.

`select_context()` remains in `RagService` because it still combines duplicate grouping, citation shaping, and context-window policy.

## What Still Remains In `RagService`

These parts are intentionally still in `services/rag_service.py`:

- request orchestration in `generate_answer()`;
- processing trace assembly;
- structured handlers such as outline, chapter summary, conflict, duplicate, document summary;
- citation/context shaping;
- manual context building;
- answer post-processing;
- small agentic workflow orchestration.

Do not move these until there is a focused test plan for each piece.

## Adaptive Chunking

`services/document_processor.py` still owns adaptive chunking light:

- structured heading chunking;
- page-aware chunking;
- recursive document chunking;
- internal scoring;
- `chunking_report` metadata for the UI inspector.

This is not a full external adaptive chunking framework. It is a lightweight local implementation for demo and observability.

## Test Commands

Run these after any AI Service refactor:

```powershell
cd D:\Project\rag-razorpages
python -m compileall AIServices\AiService -q
dotnet build D:\Project\rag-razorpages\RazorPages\EduChatbot.RazorPages\EduChatbot.RazorPages.slnx -p:OutDir=D:\Project\rag-razorpages\.tmp-build-razor\
Remove-Item D:\Project\rag-razorpages\.tmp-build-razor -Recurse -Force
```

Run guard-focused benchmark after changing `guards/`:

```powershell
cd D:\Project\rag-razorpages\AIServices\AiService
python .\run_demo_benchmark.py --subject-id 1007 --group safety,weird_input,ambiguous
```

Run full benchmark before merging:

```powershell
cd D:\Project\rag-razorpages\AIServices\AiService
python .\run_demo_benchmark.py --subject-id 1007
```

Latest verified result after this refactor:

- Python compile: pass
- RazorPages build: pass
- Guard benchmark: 15/15 pass
- Full benchmark: 74/74 pass

## Refactor Rules

- Do not import `services.rag_service` from child modules.
- Child modules should receive callbacks or plain data instead of depending on `RagService`.
- Keep wrapper methods in `RagService` when external scripts may call them.
- Do not change API response fields without updating the web app.
- Do not commit ChromaDB runtime data, uploads, benchmark result spam, or build output.
