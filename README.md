# RAG Razor Pages

This repository contains the Razor Pages submission version of EduChatbot RAG.

EduChatbot RAG is a document-grounded academic chatbot. Users upload PDF, DOCX, PPT, or PPTX learning materials, the Python AI service extracts text, creates chunks, stores vector embeddings in ChromaDB, and the chatbot answers questions using the indexed documents.

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
- RAG retrieval uses structured chunking, ChromaDB, and `Qwen/Qwen3-Embedding-0.6B` on CUDA by default. The demo machine has PyTorch CUDA installed and a GTX 1650, so indexing uses the GPU while chat generation uses Ollama.
- Chunk metadata is chapter-aware: `chapter_number`, `chapter_title`, `section_number`, `section_title`, `page_number`, and `content_zone`. This lets the chatbot answer chapter/outline questions without accidentally using table-of-contents, appendix, references, or answer-key chunks.
- Demo retrieval is tuned for the shortened sample PDFs in `sample-documents`: `sample-gomaa-software-modeling-ch1-ch2.pdf`, `sample-gomaa-software-modeling-ch1-ch2-modified-wrong.pdf`, and `sample-ddia-ch1-ch2.pdf`.
- The modified Gomaa PDF intentionally contains wrong information. It is used to demonstrate conflict-aware RAG: when original and modified sources disagree, the chatbot shows both answers grouped by source and says the sources conflict instead of deciding which one is correct.
- If another machine does not have CUDA/PyTorch GPU support, switch `EmbeddingModel` back to `intfloat/multilingual-e5-base` and `EmbeddingDevice` to `cpu` in `PresentationLayer/appsettings.json`.
- Lightweight Agentic RAG uses `qwen3:1.7b` as a small planner/checker with rule-based fallback. It rewrites short follow-up questions, creates up to three retrieval queries, checks whether evidence is sufficient, and can trigger a second retrieval round.
- A rule-based intent/document gate runs before retrieval. Non-document turns such as small talk, random text, weather, prompt-injection attempts, or vague follow-ups without history return a direct safe response with no ChromaDB search and no fake citation.
- Short follow-up questions keep the previous topic and document scope. For example, after asking about UML, `chi tiet hon` is rewritten from history and remains scoped to the Gomaa UML evidence instead of drifting into DDIA chunks.
- Hybrid retrieval runs vector, keyword, and metadata branches in parallel, then merges candidates with RRF/scoring before the selected context is sent to the local answer model.
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

Benchmark cases live in `AIServices/AiService/data/demo_benchmark_cases.json`. Reports are written to `AIServices/AiService/data/benchmark_results/` and are ignored by Git because they are runtime evidence files. The current benchmark set contains `59` cases. Earlier full verification passed the original `50/50` demo set; after that, extra guard cases were added for non-document intent and UML follow-up scope. The latest targeted verification passed the newly changed groups: `7/7` for small-talk/non-document gating plus a real Gomaa chapter question, and `2/2` for UML plus follow-up scope. The benchmark covers document listing, chapter outline, chapter summaries, section listing, follow-up questions, source conflict, duplicate content, same-name duplicate import, out-of-scope refusal, prompt-injection refusal, ambiguous acronym guards, wrong-source guards, non-document intent gating, and multi-document comparison.

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
