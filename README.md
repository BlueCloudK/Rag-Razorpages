# RAG Razor Pages

This repository contains the Razor Pages submission version of EduChatbot RAG.

EduChatbot RAG is a document-grounded academic chatbot. Users upload PDF, DOCX, PPT, or PPTX learning materials, the Python AI service extracts text, creates chunks, stores vector embeddings in ChromaDB, and the chatbot answers questions using the indexed documents.

## Portfolio Positioning

This version is positioned as a local-first AI/RAG engineering portfolio project, not just a course chatbot. The main technical story is:

- build a grounded RAG pipeline that can explain why an answer was accepted or rejected;
- evaluate retrieval, citation, conflict, duplicate, language, and safety behavior with benchmark cases;
- expose the pipeline through an operator-facing `RAG Lab` dashboard and chat trace UI;
- keep the system local by default with Ollama, ChromaDB, and HuggingFace embeddings.

## Problem

Student-facing chatbots often answer fluently but cannot prove which document chunk supports the answer. This project focuses on grounded academic QA: upload course material, index it locally, answer only from selected evidence, and show enough trace data for a lecturer, reviewer, or interviewer to inspect retrieval quality.

## Architecture

```text
Razor Pages UI
-> ServiceLayer access/subscription/chat/document rules
-> Python FastAPI AI Service
-> ingestion/chunking/contextual embedding
-> ChromaDB vector store
-> hybrid retrieval + evidence scoring
-> local Ollama answer model
-> citation and trace response
```

The Razor Pages app keeps the three-layer .NET architecture for user, subject, document, billing, and audit workflows. The Python service owns RAG-specific work: ingestion, adaptive chunking light, contextual retrieval, vector/keyword/metadata search, evidence selection, and local LLM calls.

## Repository Structure

```text
rag-razorpages/
|-- AIServices/
|   `-- AiService/                  # Python FastAPI RAG service
|-- RazorPages/
|   `-- EduChatbot.RazorPages/
|       |-- EduChatbot.RazorPages.slnx
|       |-- DataAccessLayer/        # Entities, DbContext, migrations
|       |-- ServiceLayer/           # Business logic, auth rules, AI runner
|       `-- PresentationLayer/      # ASP.NET Core Razor Pages UI
|-- Chat-flow.md
|-- Upload-flow.md
|-- RUN_VISUAL_STUDIO_2022.md
`-- README.md
```

## Main Features

- ASP.NET Core Razor Pages with 3-layer architecture.
- Authentication and role separation: Admin, Lecturer, Student.
- Organization-level subscription demo.
- Subject/course management.
- Lecturer-owned document upload and indexing.
- PDF, DOCX, PPT, PPTX support.
- RAG chat over indexed documents.
- Source citation and chunk/vector inspector.
- `RAG Lab` dashboard for benchmark quality, production metrics, pipeline status, and demo commands.
- User-scoped chat sessions and history.
- Privacy-safe audit logs.
- Local AI service using Ollama, ChromaDB, and multilingual embeddings.

## Requirements

- Visual Studio 2022.
- .NET SDK 8.0 or newer.
- SQL Server LocalDB.
- Python 3.10+.
- Ollama.

## One-Time Setup

Install Python dependencies:

```powershell
cd D:\Project\rag-razorpages\AIServices\AiService
pip install -r requirements.txt
```

Install local Ollama models:

```powershell
ollama pull gemma3:4b
ollama pull qwen2.5:3b
ollama pull qwen3:1.7b
```

## Run In Visual Studio 2022

Open:

```text
RazorPages/EduChatbot.RazorPages/EduChatbot.RazorPages.slnx
```

Set `PresentationLayer` as the startup project and run the `http` profile.

The Razor Pages app starts the Python AI service automatically from:

```text
AIServices/AiService
```

The AI service listens on:

```text
http://127.0.0.1:8000
```

## Demo Accounts

The app seeds demo accounts in Development:

| Role | Email | Password |
| --- | --- | --- |
| Admin | `admin@educhatbot.local` | `Admin@12345!` |
| Lecturer | `lecturer@educhatbot.local` | `Lecturer@12345!` |
| Student | `student@educhatbot.local` | `Student@12345!` |

## Notes For AI Optimization

- The AI service is shared through `AIServices/AiService`.
- The production-demo RAG pipeline now exposes a stable trace schema for the UI and benchmark: Guard -> Rewrite -> Query Router -> Vector/Keyword/Metadata Search -> Merge/RRF -> Evidence Scorer -> Evidence -> Local LLM -> Citation Check.
- Every RAG answer can include pipeline nodes plus evidence records with source, page, chapter, section, vector score, keyword score, metadata boost, final score, `used`, matched chunk, and context sent to the model.
- Contextual retrieval is rule-based and local-only. During indexing the service keeps the original chunk for citation/display, but embeds/searches a `contextual_text` string containing document name, chapter, section, page, heading, and a short metadata note. If the index is not rebuilt after this change, contextual retrieval is implemented but not runtime-verified for old Chroma data.
- RAG retrieval uses structured chunking, ChromaDB, and `Qwen/Qwen3-Embedding-0.6B` on CUDA by default. The demo machine has PyTorch CUDA installed and a GTX 1650, so indexing uses the GPU while chat generation uses Ollama.
- The AI service includes a lightweight adaptive chunking selector. For each document, it compares `structured_heading`, `recursive_document`, and `page_aware`, scores them with intrinsic metrics, then stores `chunking_strategy`, `chunking_score`, `chunking_reason`, and a compact `chunking_report` in chunk metadata. The document inspector UI shows the tested strategies, selected strategy, scores, and reasons so the indexing process is explainable during demo.
- Chunk metadata is chapter-aware: `chapter_number`, `chapter_title`, `section_number`, `section_title`, `page_number`, and `content_zone`. This lets the chatbot answer chapter/outline questions without accidentally using table-of-contents, appendix, references, or answer-key chunks.
- Demo retrieval is tuned for the shortened sample PDFs in `sample-documents`: `sample-gomaa-software-modeling-ch1-ch2.pdf`, `sample-gomaa-software-modeling-ch1-ch2-modified-wrong.pdf`, and `sample-ddia-ch1-ch2.pdf`.
- The modified Gomaa PDF intentionally contains wrong information. It is used to demonstrate conflict-aware RAG: when original and modified sources disagree, the chatbot shows both answers grouped by source and says the sources conflict instead of deciding which one is correct.
- If another machine does not have CUDA/PyTorch GPU support, switch `EmbeddingModel` back to `intfloat/multilingual-e5-base` and `EmbeddingDevice` to `cpu` in `PresentationLayer/appsettings.json`.
- Lightweight Agentic RAG uses `qwen3:1.7b` as a small planner/checker with rule-based fallback. It rewrites short follow-up questions, creates up to three retrieval queries, checks whether evidence is sufficient, and can trigger a second retrieval round.
- A rule-based intent/document gate runs before retrieval. Non-document turns such as small talk, random text, weather, prompt-injection attempts, or vague follow-ups without history return a direct safe response with no ChromaDB search and no fake citation.
- Short follow-up questions keep the previous topic and document scope. For example, after asking about UML, `chi tiet hon` is rewritten from history and remains scoped to the Gomaa UML evidence instead of drifting into DDIA chunks.
- Query decomposition handles comparison and multi-document questions. For example, `So sanh chuong 1 cua Gomaa va DDIA` is split into separate Gomaa and DDIA retrieval queries, then the selected evidence is merged before answer generation. This is local rule-based decomposition, not full multi-agent RAG.
- The same decomposition layer also handles chapter-vs-chapter comparisons, pros/cons questions, and process/workflow questions by creating focused subqueries before hybrid retrieval.
- Hybrid retrieval runs vector, keyword, and metadata branches in parallel, then merges candidates with RRF/scoring before the selected context is sent to the local answer model.
- Evidence selection uses lightweight scoring by default, combining vector score, keyword score, metadata boost, exact/heading matches, and duplicate/conflict adjustments. Heavy cross-encoder reranking is optional through config and remains disabled by default.
- Citation verification is answer-level/evidence-level: only selected evidence with `used=true` is shown as a citation. Low-confidence or blocked answers return without fake sources.
- The trace now includes a `citation_verification` block with verified source labels, rejected labels if any, and selected evidence counts.
- Selected child chunks are expanded into a bounded context window before the local LLM sees them. The trace separates `matched_chunk` from `context_sent`, so the demo can show what matched and what was actually sent to the model.
- Optional cross-encoder reranking is wired but off by default: keep `RagEnableReranker=false` for GTX 1650/4GB VRAM demos, or set it to `true` to run `Qwen/Qwen3-Reranker-0.6B` on CPU for slower quality experiments.
- `gemma3:4b` writes the final answer, with `qwen2.5:3b` as fallback. The tested `qwen3:4b` tag can return thinking text or empty responses through Ollama on this machine, so it is not the default demo answer model.
- Ollama is used for local answer generation.
- ChromaDB is runtime development data. When embedding model, chunking, or metadata rules change, delete `AIServices/AiService/chroma_db` and re-index the documents.
- Runtime data such as uploaded files, ChromaDB, LocalDB files, build outputs, and IDE folders are intentionally ignored.

## Demo RAG Benchmark

Index the demo documents into the AI service. Use the same `subject-id` as the subject you want to test in the web app; the latest local verification used `1007`:

```powershell
cd D:\Project\rag-razorpages\AIServices\AiService
python .\index_demo_documents.py --reset --subject-id 1007
```

The script indexes these demo sources:

```text
sample-gomaa-software-modeling-ch1-ch2.pdf                         # original
sample-gomaa-software-modeling-ch1-ch2-duplicate.pdf               # same content, different demo name
sample-gomaa-software-modeling-ch1-ch2.pdf (demo-gomaa-same-name)  # same content, same display name, different document id
sample-gomaa-software-modeling-ch1-ch2-modified-wrong.pdf          # intentionally wrong variant
sample-ddia-ch1-ch2.pdf                                            # second book
```

Run all benchmark cases:

```powershell
python .\run_demo_benchmark.py --subject-id 1007
```

Run selected cases quickly:

```powershell
python .\run_demo_benchmark.py --subject-id 1007 --ids ambiguous_wc_vi,conflict_gomaa_ch2_vi,duplicate_gomaa_ch2_same_content_vi
```

Run by group during development:

```powershell
python .\run_demo_benchmark.py --subject-id 1007 --group safety,weird_input,ambiguous
python .\run_demo_benchmark.py --subject-id 1007 --group chapter,summary,section,followup
python .\run_demo_benchmark.py --subject-id 1007 --group conflict,duplicate,multi_doc,wrong_source
```

Benchmark cases live in `AIServices/AiService/data/demo_benchmark_cases.json`. Reports are written to `AIServices/AiService/data/benchmark_results/` and are ignored by Git because they are runtime evidence files. The benchmark now reports both classic pass/fail and production-style metrics: retrieval hit, source correctness, citation precision, answer coverage, hallucination guard, conflict handling, duplicate handling, and language quality. It covers document listing, chapter outline, chapter summaries, section listing, follow-up questions, source conflict, duplicate content, same-name duplicate import, out-of-scope refusal, prompt-injection refusal, ambiguous acronym guards, wrong-source guards, non-document intent gating, and multi-document comparison.

Latest local verification after re-indexing contextual retrieval:

```text
Full benchmark: 74/74 passed
Python compile: pass
RazorPages build: pass
```

## RAG Lab Dashboard

Admins can open `/RagLab` to see the project as an AI engineering demo surface:

- latest benchmark pass rate and production score;
- group-level scores for safety, follow-up, conflict, duplicate, source guard, and chapter/summary behavior;
- metric scores for retrieval hit, source correctness, citation precision, answer coverage, hallucination guard, conflict handling, duplicate handling, and language quality;
- indexed demo corpus and chunk counts;
- good answer examples, failed cases if any, and commands to re-index or rerun benchmark.

The dashboard reads the latest ignored benchmark JSON report. It does not commit runtime reports and does not run long benchmark jobs from a web request.

## AI Circuit Live

The chat page includes an `AI Circuit Live` panel for demonstrations. It is a visual processing map, not just a loading animation. The compact right-side panel shows the live path for the current question:

```text
Gate and query:
Question -> Scope/intent gate -> Rewrite/history

Parallel retrieval loop:
Vector search + Keyword/BM25 search + Metadata search
-> RRF/scoring merge

Evidence and answer:
Context window -> Local LLM -> Citations
```

The `Details` button opens a larger system-map modal. It includes:

- an indexing reference: upload, extract text, structured chunking, Qwen embedding, SQL/ChromaDB storage;
- the runtime trace for the current question: intent, subject scope, rewritten query, retrieval rounds, branch timings, candidate counts, selected evidence, confidence, answer model, and citations;
- skipped/blocked states for greetings, random small talk, prompt injection, or weak evidence. In those cases ChromaDB nodes are marked skipped and no fake source is attached.

The trace intentionally does not display hidden prompts or chain-of-thought. It only exposes operational metadata that helps explain how RAG chose or rejected evidence.

## RAG Capability Matrix

| Capability | Current behavior |
| --- | --- |
| Chapter and outline questions | Uses chapter-aware metadata before normal retrieval, so it can answer which chapters/sections exist in the indexed sample. |
| Follow-up questions | Uses chat history and rule/small-planner fallback to rewrite short follow-ups such as `liet ke ra giup toi` or `chi tiet hon`, while keeping the previous topic/document scope. |
| Citation | Returns source files and chunk metadata. The UI groups sources instead of showing raw file tags only. |
| Conflict awareness | If original and modified variants disagree, the answer is grouped by source and explicitly warns about conflict. It does not decide which source is true unless trusted metadata is added later. |
| Duplicate awareness | Identical chunks get `content_hash` metadata. Retrieval sends one representative chunk to the LLM, but citations list all files/doc ids containing the same content. |
| Same-name duplicate handling | Normal web upload rejects another file with the same name in the same subject. The AI service still handles same-name duplicate imports safely by including document ids in duplicate source labels. |
| Safety guards | Prompt injection, random/gibberish input, weather/shopping/creative requests, and weak ambiguous acronym questions are blocked or clarified without fake sources. |
| Non-document intent gate | Questions that do not look like learning/document questions do not run retrieval and do not show source citations. |
| AI trace visibility | The chat UI visualizes intent, rewrite, parallel retrieval branches, rerank/context selection, local model generation, and citation attachment. |

## Information Quality Evaluation

The benchmark does not prove the chatbot is perfect; it proves the current demo handles the risk groups we defined. We evaluate answer quality with these checks:

- `Source correctness`: the answer should cite the expected file, chapter, and page/section when available.
- `Evidence sufficiency`: selected chunks must contain enough direct evidence; weak matches are blocked or clarified.
- `Answer completeness`: chapter summaries should cover the main ideas, not just copy a random sentence.
- `Conflict awareness`: different source variants should be shown separately with a conflict warning.
- `Duplicate awareness`: identical sources should be merged for the LLM while still listed in citations.
- `Safety`: out-of-scope, prompt-injection, answer-key, wrong-source, and vague acronym questions should not hallucinate sources.

## Current Limitations

- Benchmark pass rates are for the curated demo set, not a guarantee for every textbook or OCR quality.
- Local models can be slow, especially when `gemma3:4b` is asked to synthesize long answers.
- Scanned PDFs or badly extracted text can still produce poor chunks.
- The conflict policy reports disagreement; it does not know which document is official unless a future `trusted=true` metadata rule is added.
- Duplicate detection is chunk-level content hashing, so near-duplicates with paraphrased wording are not always merged.

## Future Work

- Stream trace events from Python to the UI with SSE or SignalR instead of showing only the completed trace.
- Add optional stronger reranking for machines with more CPU/GPU headroom.
- Add OCR/document-layout backends for scanned PDFs and table-heavy documents.
- Add trusted-source metadata so the system can prefer an official document when conflict is detected.
- Expand benchmark coverage beyond the curated demo PDFs with more real course materials.

## Why This Is Not Just A Chatbot Wrapper

The project does not simply send a prompt to an LLM. It has local ingestion, adaptive chunking light, contextual embedding, hybrid retrieval, evidence scoring, duplicate/conflict handling, grounded citation verification, a benchmark suite, and an observability dashboard. The LLM is only the final answer synthesizer after evidence is selected.
