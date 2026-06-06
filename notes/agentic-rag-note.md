# Agentic RAG Note

This note summarizes the Agentic RAG idea and how it can be adapted for EduChatbot.

## What Google Announced

Google Research published an article on June 5, 2026 about Agentic RAG for Gemini Enterprise Agent Platform.

It is not a new local model. It is a RAG architecture that uses agent-style workflow to make retrieval more dependable.

Source:

```text
https://research.google/blog/unlocking-dependable-responses-with-gemini-enterprise-agent-platforms-agentic-rag/
```

## Standard RAG

```text
User question
-> retrieve top-k chunks
-> send chunks to LLM
-> answer
```

Standard RAG is simple and fast, but it can fail when the question needs multiple pieces of evidence from different documents or different parts of a document.

## Agentic RAG

```text
User question
-> planner analyzes the question
-> query rewriter creates better search queries
-> retriever searches one or more sources
-> context checker decides if evidence is enough
-> if missing evidence, search again
-> answer generator writes final answer
-> source checker keeps answer grounded
```

The key idea is not retrieving once and answering immediately. The system checks whether the retrieved context is sufficient before generating the final response.

## Important Components

### Query Planner

Breaks a complex question into smaller search goals.

Example:

```text
"Compare chapter 1 and chapter 2"
-> "chapter 1 main ideas"
-> "chapter 2 main ideas"
-> "differences between chapter 1 and chapter 2"
```

### Query Rewriter

Turns vague or conversational questions into searchable queries.

Example:

```text
"explain more"
-> "explain the previous topic in this subject using indexed documents"
```

### Retriever

Searches ChromaDB using vector search and keyword search.

### Sufficient Context Checker

Checks whether the retrieved chunks contain enough evidence to answer.

Possible output:

```json
{
  "sufficient": false,
  "missing": ["chapter 2 details"],
  "follow_up_queries": ["chapter 2 summary", "chapter 2 key concepts"]
}
```

### Answer Generator

Uses the final selected chunks to answer.

## Practical Version For EduChatbot

Because the machine has 4GB VRAM, do not run many real agents. Use one local LLM in several steps.

Recommended lightweight pipeline:

```text
1. Rewrite or plan query
2. Retrieve top candidates
3. Select best chunks
4. Check if context is enough
5. If not enough, run one extra retrieval round
6. Generate answer with citations
```

Recommended limits:

```text
max_retrieval_rounds = 2
max_sub_queries = 3
final_chunks = 3-5
LLM = qwen3:4b
Embedding = Qwen/Qwen3-Embedding-0.6B
Reranker = optional CPU
```

## Implemented Lightweight Version

The RazorPages submission repo implements a low-cost version:

```text
RAG_ENABLE_AGENTIC = true
RAG_AGENTIC_MAX_ROUNDS = 2
RAG_AGENTIC_MAX_SUBQUERIES = 3
```

The planner and context checker are rule-based instead of LLM-based. This keeps the workflow cheap for a 4GB VRAM machine:

```text
question
-> rule-based query planner
-> vector + keyword retrieval for each planned query
-> merge ranked chunks
-> rule-based context sufficiency check
-> optional second retrieval round
-> qwen3:4b final answer
```

Only the final answer calls the local LLM. The planner/checker do not load another model.

## Why It Helps EduChatbot

Agentic-style RAG can improve:

- questions that compare multiple chapters
- questions that ask for summaries across multiple files
- questions where the first retrieval misses important context
- source-grounded answers
- refusal quality when documents do not contain enough evidence

## Suggested Presentation Line

EduChatbot can be extended from standard RAG to lightweight Agentic RAG. Instead of retrieving once, the system plans the query, retrieves evidence, checks if the context is sufficient, and performs a second retrieval if needed before generating a grounded answer.
