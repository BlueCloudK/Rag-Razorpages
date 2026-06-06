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

The web app starts `D:\Project\PRN222\AIServices\AiService` on:

```text
http://127.0.0.1:8000
```

## LLM Provider

Default mode is local-only:

```powershell
ollama pull qwen3:4b
ollama pull gemma3:4b
```

The shared AI service uses `qwen3:4b` as the primary local answer model, `gemma3:4b` as local fallback, `Qwen/Qwen3-Embedding-0.6B` for embeddings, and `BAAI/bge-reranker-v2-m3` for optional CPU reranking.
