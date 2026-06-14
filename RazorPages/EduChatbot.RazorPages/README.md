# EduChatbot Razor Pages - Three-Layer Architecture

This solution follows the same three-layer structure as the MVC version:

```text
EduChatbot.RazorPages/
|-- DataAccessLayer/      # Entities and DbContext
|-- ServiceLayer/         # Application services and AI service runner
`-- PresentationLayer/    # ASP.NET Core Razor Pages UI, config, and wwwroot

..\..\AIServices/
`-- AiService/            # Python FastAPI RAG service used by the web app
```

## Layer Responsibilities

- `DataAccessLayer`: database entities, ASP.NET Core Identity entities, subscription entities, `ApplicationDbContext`, and EF Core migrations.
- `ServiceLayer`: application logic, role checks, subject membership checks, subscription quota checks, user-scoped chat history, document ownership, and Python AI backend startup.
- `PresentationLayer`: Razor Pages UI, PageModels, configuration, and static assets. It uses `[Authorize]` and service interfaces only.
- `AIServices/AiService`: standalone Python FastAPI service for document reading, chunking, embeddings, and RAG chat. It is outside this C# solution and is developed separately.

## Authentication and Subscription

Development seeds these accounts:

| Role | Email | Password |
| --- | --- | --- |
| Admin | `admin@educhatbot.local` | `Admin@12345!` |
| Lecturer | `lecturer@educhatbot.local` | `Lecturer@12345!` |
| Student | `student@educhatbot.local` | `Student@12345!` |

Roles control permissions. Subscriptions control usage quota at organization level. Legacy user subscription tables may exist for database compatibility, but runtime quota decisions use the active organization plan.

| Plan | Questions/day | Documents | File size | Subjects | Gemini |
| --- | ---: | ---: | ---: | ---: | --- |
| Free | 20 | 3 | 5 MB | 1 | No |
| Pro | 300 | 50 | 50 MB | 10 | Yes |
| Organization | High/unlimited demo quota | High/unlimited demo quota | 200 MB | High/unlimited demo quota | Yes |

Admin creates subjects, manages users, subject memberships, and privacy-safe activity logs, but does not upload or delete lecturer documents. Lecturer can upload/delete documents only in assigned subjects and cannot delete subjects. Student can only chat in enrolled subjects. Chat sessions are scoped by `SubjectId + UserId`, and users can create, reopen, and delete their own subject chat sessions.

## Audit and Index Inspector

- Admin Activity at `/Admin/Activity` shows login/register, account changes, subject access, upload/index/delete document events, and chat usage counts.
- Audit logs do not store question text, AI answers, or document content.
- Indexed documents in the chat sidebar include an inspector popup showing where metadata is stored in SQL Server and how chunks/vectors are stored in ChromaDB.

## Run

Open:

```text
EduChatbot.RazorPages.slnx
```

Set `PresentationLayer` as the startup project and run with Visual Studio 2022. The solution only contains the three C# layers.

On first run, EF Core migrations update LocalDB and seed roles, plans, and demo accounts.

Default web URL:

```text
http://localhost:5101
```

The web app starts the shared Python AI service from this repository:

```text
D:\Project\rag-razorpages\AIServices\AiService
```

The AI service listens on:

```text
http://127.0.0.1:8000
```

## LLM Provider

Default mode is local-only:

```powershell
ollama pull gemma3:4b
ollama pull qwen2.5:3b
ollama pull qwen3:1.7b
```

The shared AI service uses structured chunking, `Qwen/Qwen3-Embedding-0.6B` on CUDA for embeddings, ChromaDB for vector storage, `qwen3:1.7b` as a small planner/checker with rule-based fallback, and `gemma3:4b` as the primary local answer model. `qwen2.5:3b` is kept as answer fallback. On this demo machine PyTorch CUDA sees the GTX 1650, so indexing can use the GPU. If another machine is CPU-only, switch `EmbeddingModel` back to `intfloat/multilingual-e5-base` and `EmbeddingDevice` to `cpu`. Agentic RAG is limited to two retrieval rounds and three sub-queries.

Before retrieval, the AI service runs an intent/document gate. Only document-learning questions enter RAG. Small talk, random text, weather questions, prompt injection, and vague follow-ups without history are answered directly with no ChromaDB search and no fake sources. Short follow-up questions with history are rewritten into standalone queries and keep the previous document/topic scope; for example, after a UML question, `chi tiet hon` stays scoped to Gomaa UML chunks instead of drifting into DDIA.

Retrieval uses three lightweight branches in parallel:

```text
Vector search + Keyword/BM25 search + Metadata search
-> RRF/scoring rerank
-> selected context chunks
-> local answer model
```

Chunk metadata includes `chapter_number`, `chapter_title`, `section_number`, `section_title`, `page_number`, and `content_zone`. Chapter and outline questions use this metadata first, so the chatbot avoids using table-of-contents, appendix, references, or answer-key chunks as evidence for chapter content.

The AI service also records an adaptive chunking report for every newly indexed document. It compares `structured_heading`, `recursive_document`, and `page_aware`, then stores the selected strategy, score, reason, and tested strategy metrics in ChromaDB metadata. In the document inspector, the `Adaptive chunking decision` panel shows this report so the indexing step is explainable instead of looking like a fixed splitter.

ChromaDB is runtime development data; when embedding or chunking changes, stop the web app/Python service, delete `AIServices/AiService/chroma_db`, and re-index the documents.

## Demo Benchmark

The repo includes shortened sample PDFs in `sample-documents` for fast local testing:

```text
sample-gomaa-software-modeling-ch1-ch2.pdf
sample-gomaa-software-modeling-ch1-ch2-modified-wrong.pdf
sample-ddia-ch1-ch2.pdf
```

`index_demo_documents.py` also indexes two duplicate Gomaa entries for evaluation: one with a different demo name and one with the same display name but a different internal document id. This proves that duplicate handling is based on content hash and document id, not only on file name.

The modified Gomaa sample intentionally contains wrong information. It demonstrates conflict-aware RAG: when the original and modified documents disagree, the chatbot groups the answer by source, cites both files, and warns that the sources conflict instead of choosing which version is correct.

Index the demo documents directly into the AI service:

```powershell
cd D:\Project\rag-razorpages\AIServices\AiService
python .\index_demo_documents.py --reset --subject-id 1007
```

Run the full demo benchmark:

```powershell
python .\run_demo_benchmark.py --subject-id 1007
```

Run selected cases quickly:

```powershell
python .\run_demo_benchmark.py --subject-id 1007 --ids ambiguous_wc_vi,conflict_gomaa_ch2_vi,duplicate_gomaa_ch2_same_content_vi
```

Benchmark cases are in `AIServices/AiService/data/demo_benchmark_cases.json`; runtime reports are written to `AIServices/AiService/data/benchmark_results/` and ignored by Git. The benchmark set currently contains `59` cases. Earlier full verification passed the original `50/50` demo set; newer targeted checks passed `7/7` for small-talk/non-document gating and `2/2` for UML follow-up scope. The cases include conflict handling, duplicate content grouping, same-name duplicate import handling, ambiguous acronym guards, prompt-injection refusal, wrong-source guards, non-document intent gating, scoped follow-ups, and out-of-scope refusal.

## AI Circuit Live

The chat workspace includes a right-side `AI Circuit Live` panel. It is designed for demo and debugging, not just decoration. It shows the current question as a visual system map:

```text
Gate and query
Question -> Scope/intent -> Rewrite/history

Parallel retrieval
Vector + Keyword/BM25 + Metadata -> RRF/scoring

Evidence and answer
Context chunks -> Local model -> Citations
```

The compact panel shows status, intent, retrieval rounds, evidence count, and source count. The `Details` modal expands it into a clearer technical map:

- indexing reference: upload, extract, chunk, embed, store in SQL/ChromaDB;
- runtime trace: scope decision, rewritten query, retrieval branches, branch timings, candidate counts, selected chunks, model, confidence, fallback, and citations;
- blocked/skipped path for greetings, random input, prompt injection, and weak evidence.

The trace is operational metadata only. It does not expose hidden prompts or chain-of-thought.

## RAG Capability Matrix

| Capability | Current behavior |
| --- | --- |
| Chapter and outline questions | Uses chapter-aware metadata before normal retrieval. |
| Follow-up questions | Rewrites short follow-ups using history and small planner/rule fallback, while preserving previous document/topic scope. |
| Citation | Returns source files plus chunk metadata for UI source grouping. |
| Conflict awareness | Shows original/modified answers separately and warns about conflict. |
| Duplicate awareness | Uses `content_hash` to send one representative chunk to the LLM while listing all duplicate sources. |
| Same-name duplicate upload | Normal web upload blocks duplicate file names inside the same subject. AI import still labels same-name duplicates by document id. |
| Safety guards | Blocks or clarifies prompt injection, vague acronyms, random input, and out-of-scope questions without fake citations. |
| Non-document intent gate | Skips retrieval for questions that are not about learning material, so random chat does not produce fake document citations. |
| AI trace visibility | Shows retrieval branches, rerank/context selection, answer model, confidence, and citations in the chat UI. |

## Information Quality Evaluation

The benchmark evaluates practical demo quality rather than general intelligence:

- `Source correctness`: expected file/chapter/page appears in sources or selected contexts.
- `Evidence sufficiency`: weak evidence is blocked or clarified instead of answered confidently.
- `Answer completeness`: summaries should contain the main ideas, not just a raw copied sentence.
- `Conflict awareness`: different variants are separated and not silently merged.
- `Duplicate awareness`: identical content is merged for context but kept visible in citations.
- `Safety`: prompt injection, wrong-source questions, answer-key requests, and out-of-scope questions do not create fake sources.

## Current Limitations

- Benchmark pass rates are scoped to the curated demo set.
- Local generation can be slow on small hardware.
- OCR/scanned PDFs can still hurt chunk quality.
- Conflict handling does not decide the official source yet; add trusted metadata if that becomes a requirement.
- Duplicate detection is exact normalized chunk hashing, not semantic near-duplicate detection.
