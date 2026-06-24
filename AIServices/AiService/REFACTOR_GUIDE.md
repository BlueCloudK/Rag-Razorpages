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

The current production-demo trace contract is `rag_trace_v2`. It adds stable pipeline nodes and evidence records for the web UI and benchmark while keeping the old top-level response fields compatible.

The Razor Pages app also includes an admin-only `RAG Lab` page. It reads the latest ignored benchmark JSON report and visualizes pass rate, production metrics, group scores, corpus status, good examples, failed cases, and demo commands. The page is read-only; long benchmark jobs still run through the CLI.

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

`RagService` also owns the final lightweight evidence scoring step because it combines retrieval scores with routing, duplicate/conflict policy, and citation verification.

## What Still Remains In `RagService`

These parts are intentionally still in `services/rag_service.py`:

- request orchestration in `generate_answer()`;
- processing trace assembly;
- query routing metadata (`route_query()`), because it coordinates guards and retrieval policies;
- contextual retrieval text generation (`build_contextual_text()`), because it depends on chunk metadata and index-time storage;
- structured handlers such as outline, chapter summary, conflict, duplicate, document summary;
- citation/context shaping;
- evidence scoring, context expansion, and answer-level citation verification;
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

## Contextual Retrieval

Indexing stores original chunk text as the Chroma document for display/citation, but embeds a rule-generated `contextual_text` value. The metadata also stores:

- `original_text`
- `contextual_text`
- `context_source=rule_based`

Old Chroma indexes do not contain this metadata. After changing contextual retrieval, delete runtime ChromaDB and re-index demo documents before judging runtime quality.

## Evidence And Citation Verification

Trace evidence records include source, page, chapter, section, vector score, keyword score, metadata boost, final score, `used`, matched chunk, and context sent to the model.

Only evidence marked `used=true` should become a citation. Candidate rows with `used=false` are kept for observability but must not be rendered as sources for the final answer.

`RAG Lab` consumes benchmark reports that include the same trace/evidence fields. If the response contract changes, update both the chat UI trace renderer and the benchmark report reader in the Razor Pages ServiceLayer.

## Query Router

`route_query()` is a rule-based router. It records `intent`, `routing_decision`, and `retrieval_policy` in `processing_trace`. It does not call a cloud model and does not implement multi-agent routing.

`decompose_query()` is a small rule-based planner for comparison and multi-document prompts. It creates a few focused retrieval queries, such as one query for Gomaa and one query for DDIA, then `retrieve_query_context_agentic()` pins the best evidence from each subquery before normal evidence scoring. This prevents one strong source from hiding the other source in comparison answers. It is query decomposition, not real multi-agent RAG.

The decomposition layer also covers:

- chapter-vs-chapter comparisons;
- pros/cons questions, split into benefits and limitations;
- process/workflow questions, split into definition/components and steps.

Citation verification lives in `verify_citations()`. It compares displayed source labels with selected evidence records and writes `citation_verification` into `processing_trace`. UI source blocks and benchmark checks should rely on verified/used evidence, not candidate-only rows.

The optional cross-encoder reranker is wired through `RAG_ENABLE_RERANKER` and `RERANKER_MODEL`, but remains off by default. Keep that default unless you explicitly want a slower CPU rerank experiment.

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
