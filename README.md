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
ollama pull qwen3:4b
ollama pull gemma3:4b
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
- RAG retrieval uses ChromaDB and `intfloat/multilingual-e5-base`.
- Ollama is used for local answer generation.
- Runtime data such as uploaded files, ChromaDB, LocalDB files, build outputs, and IDE folders are intentionally ignored.
