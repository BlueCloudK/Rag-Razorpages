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
-> embed question
-> retrieve related chunks
-> send selected chunks to qwen3:4b
-> generate grounded answer with sources
```

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

1. The question is embedded with the same embedding model.
2. ChromaDB compares the question vector with document chunk vectors.
3. The closest chunks are retrieved.
4. Keyword search also runs to catch exact terms such as chapter names, file names, and technical keywords.
5. The system combines vector search and keyword search.
6. The best chunks are used as context for the answer model.

## Answer Generation

The answer model is:

```text
qwen3:4b
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

EduChatbot uses RAG, not fine-tuning. Uploaded documents are split into chunks and embedded with `Qwen/Qwen3-Embedding-0.6B`. The vectors are stored in ChromaDB. When a user asks a question, the system embeds the question, retrieves the most relevant chunks, and uses `qwen3:4b` to generate an answer grounded in those chunks.
