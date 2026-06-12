# Embedding And RAG Flow

This note explains how EduChatbot reads documents, embeds them, and answers questions.

## Short Version

EduChatbot does not fine-tune the language model. It uses RAG:

```text
Upload document
-> extract text
-> split text into chunks
-> embed each chunk into vectors
-> store chunks, vectors, and metadata in ChromaDB

User question
-> intent/document gate
-> rewrite short follow-up if needed
-> embed question
-> retrieve related chunks with vector + keyword + metadata search
-> rerank/merge candidates
-> send selected chunks to gemma3:4b
-> generate grounded answer with sources
```

The chat UI visualizes this runtime path in `AI Circuit Live`. The compact panel shows the main path; the details modal shows the same path as a system map with indexing reference, retrieval rounds, branch timings, candidate counts, selected evidence, model, confidence, and citation decisions.

## Upload And Indexing

When a lecturer uploads a PDF, DOCX, or PPTX:

1. Python AI Service extracts text from the file.
2. The text is cleaned and split into chunks.
3. Current chunk config:

```text
chunk_size = 850
chunk_overlap = 120
```

Overlap keeps context between adjacent chunks, so an idea split across two chunks is less likely to be lost.

## Embedding

Each chunk is passed through the embedding model:

```text
Qwen/Qwen3-Embedding-0.6B
```

The embedding model does not answer questions. It converts text into a vector, which is a list of numbers representing semantic meaning.

Example:

```text
"Software testing verifies software quality"
-> [0.021, -0.114, 0.372, ...]
```

The system stores this in ChromaDB:

```text
chunk text
embedding vector
document_id
document_name
subject_id
chunk_index
page_number / slide_number
embedding_model
```

## Asking A Question

When the user asks a question:

1. The intent gate checks whether the input is a document-learning question.
2. Short follow-ups are rewritten from chat history when possible.
3. The question is embedded with the same embedding model.
4. Vector search, keyword/BM25 search, and metadata search run in parallel.
5. The system merges candidates with RRF/scoring and selects the best chunks.
6. The best chunks are used as context for the answer model.

The trace shown in the UI is operational metadata:

```text
Question
-> Scope/intent decision
-> Rewrite/history
-> Vector branch
-> Keyword branch
-> Metadata branch
-> RRF/scoring merge
-> Context window
-> Local LLM
-> Citations
```

If the intent gate decides the message is not a learning/document question, the retrieval branches are skipped. This is why random chat, weather questions, prompt-injection attempts, or vague text should not produce fake document sources.

## Answer Generation

The answer model is:

```text
gemma3:4b
```

It receives only the retrieved context, not the whole document.

Conceptual prompt:

```text
Answer only from the context.
If the context is not enough, say the document does not contain enough information.
Cite source documents when possible.

CONTEXT:
[chunk 1]
[chunk 2]
[chunk 3]

QUESTION:
...
```

## Why Re-index Is Required After Changing Embedding Model

Vectors from different embedding models are not compatible. If the old database used `intfloat/multilingual-e5-base` and the new one uses `Qwen/Qwen3-Embedding-0.6B`, the old vectors should be deleted and documents should be uploaded again.

To reset local ChromaDB:

```powershell
Remove-Item -Recurse -Force D:\Project\rag-razorpages\AIServices\AiService\chroma_db
```

Then run the app and upload documents again.

## Simple Explanation For Presentation

EduChatbot uses RAG, not fine-tuning. Uploaded documents are split into chunks and embedded with `Qwen/Qwen3-Embedding-0.6B`. The vectors are stored in ChromaDB. When a user asks a question, the system first checks intent, rewrites follow-ups when needed, retrieves with vector/keyword/metadata search, reranks selected chunks, and uses `gemma3:4b` to generate an answer grounded in those chunks. If the question is not about the indexed learning material, retrieval is skipped and no source is attached. The `AI Circuit Live` panel shows this process visually so a teacher can see whether the system used document evidence or blocked the question safely.
