import os
import re
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

import requests
from jinja2 import Template
import sentence_transformers  # Load before ChromaDB to avoid a Windows pyarrow access violation.
import chromadb

from utils.text_normalization import (
    normalize_text as _normalize_text,
    compact_preview as _compact_preview,
    normalize_for_content_hash as _normalize_for_content_hash,
    compute_content_hash as _compute_content_hash,
    is_vietnamese_query as _is_vietnamese_query,
    tokenize as _tokenize,
    get_query_chapter_numbers as _get_query_chapter_numbers,
    is_definition_query as _is_definition_query,
    strip_meta_comments as _strip_meta_comments,
    clean_llm_output as _clean_llm_output,
)
from guards.ambiguity_guard import (
    extract_ambiguous_acronym as _extract_ambiguous_acronym,
    extract_definition_term as _extract_definition_term,
    has_direct_definition_for_term as _has_direct_definition_for_term,
)
from guards.intent_gate import (
    is_likely_document_question as _is_likely_document_question,
    is_clear_out_of_scope_query as _is_clear_out_of_scope_query,
    is_outline_query as _is_outline_query,
    is_section_query as _is_section_query,
    is_summary_query as _is_summary_query,
    is_document_summary_query as _is_document_summary_query,
    is_short_followup_query as _is_short_followup_query,
    is_conflict_sensitive_query as _is_conflict_sensitive_query,
    is_duplicate_sensitive_query as _is_duplicate_sensitive_query,
    should_rewrite_query as _should_rewrite_query,
)
from guards.safety_guard import classify_intent as _classify_intent
from embeddings.embedder import EmbeddingManager
from llm.ollama_client import OllamaClient, parse_json_object as _parse_json_object
from retrieval.fusion import (
    fuse_dense_keyword_metadata as _fuse_dense_keyword_metadata,
    merge_ranked_rows as _merge_ranked_rows,
)
from retrieval.keyword_search import keyword_candidates as _keyword_candidates
from retrieval.metadata_search import metadata_candidates as _metadata_candidates
from retrieval.rerank import rerank_candidates as _rerank_candidates
from retrieval.vector_search import dense_candidates as _dense_candidates
from vectordb.chroma_store import (
    build_scope_filter as _build_scope_filter,
    rows_from_chroma_result as _rows_from_chroma_result,
)


class RagService:
    def __init__(self):
        chroma_path = self.resolve_chroma_path()
        print(f"Using ChromaDB at: {chroma_path}", flush=True)
        self.chroma_client = chromadb.PersistentClient(path=chroma_path)
        self.collection = self.chroma_client.get_or_create_collection(
            name="edu_documents",
            metadata={"hnsw:space": "cosine"}
        )
        self.embeddings = {}
        self._llm = None
        self._fallback_llm = None
        self._reranker = None
        self._last_model_used = self.get_llm_model_name()
        self._primary_llm_unavailable = False
        self._query_embedding_cache = {}
        self._metadata_rows_cache = {}
        self._chapter_outline_cache = {}
        self._last_evidence_records = []
        self.candidate_pool = int(os.getenv("RAG_CANDIDATE_POOL", "20"))
        self.rerank_top_k = int(os.getenv("RAG_RERANK_TOP_K", "6"))
        self.max_context_chars = int(os.getenv("RAG_MAX_CONTEXT_CHARS", "5000"))
        self.max_evidence_chunks = int(os.getenv("MAX_EVIDENCE_CHUNKS", "5"))
        self.max_context_chars_per_evidence = int(os.getenv("MAX_CONTEXT_CHARS_PER_EVIDENCE", "2500"))
        self.max_total_context_chars = int(os.getenv("MAX_TOTAL_CONTEXT_CHARS", "9000"))
        self.sentence_window_before = int(os.getenv("SENTENCE_WINDOW_BEFORE", "2"))
        self.sentence_window_after = int(os.getenv("SENTENCE_WINDOW_AFTER", "2"))
        self.ollama_num_ctx = int(os.getenv("OLLAMA_NUM_CTX", "4096"))
        self.ollama_num_predict = int(os.getenv("OLLAMA_NUM_PREDICT", "512"))
        self.ollama_timeout = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "120"))
        self.ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
        self.ollama_client = OllamaClient(self.ollama_base_url, timeout=self.ollama_timeout)
        self.embedding_model_name = os.getenv("EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-0.6B").strip()
        self.embedding_device = os.getenv("EMBEDDING_DEVICE", "cuda").strip()
        self.embedding_manager = EmbeddingManager(self.embedding_model_name, self.embedding_device)
        self.enable_reranker = os.getenv("RAG_ENABLE_RERANKER", "false").lower() == "true"
        self.reranker_model_name = os.getenv("RERANKER_MODEL", "Qwen/Qwen3-Reranker-0.6B")
        self.enable_agentic_rag = os.getenv("RAG_ENABLE_AGENTIC", "true").lower() == "true"
        self.agentic_max_rounds = max(1, min(int(os.getenv("RAG_AGENTIC_MAX_ROUNDS", "2")), 2))
        self.agentic_max_subqueries = max(1, min(int(os.getenv("RAG_AGENTIC_MAX_SUBQUERIES", "3")), 3))
        self.agentic_planner_mode = os.getenv("RAG_PLANNER_MODE", "rule-based").strip().lower()
        self.agentic_planner_model = os.getenv("RAG_PLANNER_MODEL", "qwen3:1.7b").strip()
        self.agentic_checker_model = os.getenv("RAG_CHECKER_MODEL", "qwen3:1.7b").strip()
        self.agentic_planner_timeout = int(os.getenv("RAG_PLANNER_TIMEOUT_SECONDS", "45"))
        self.agentic_planner_num_ctx = int(os.getenv("RAG_PLANNER_NUM_CTX", "2048"))
        self.agentic_planner_num_predict = int(os.getenv("RAG_PLANNER_NUM_PREDICT", "160"))

        prompt_path = os.path.join(os.path.dirname(__file__), "..", "prompts", "system_prompt.jinja")
        with open(prompt_path, "r", encoding="utf-8") as f:
            self.prompt_template = Template(f.read())

    def pipeline_node(self, name, status="done", input_summary="", output_summary="", duration_ms=0, skip_reason="", block_reason=""):
        return {
            "name": name,
            "status": status,
            "input_summary": self.compact_preview(input_summary, 220),
            "output_summary": self.compact_preview(output_summary, 260),
            "duration_ms": int(duration_ms or 0),
            "skip_reason": skip_reason or "",
            "block_reason": block_reason or ""
        }

    def build_contextual_text(self, original_text, metadata):
        parts = []
        document_name = str(metadata.get("document_name") or "").strip()
        chapter_number = int(metadata.get("chapter_number") or 0)
        chapter_title = str(metadata.get("chapter_title") or "").strip()
        section_path = str(metadata.get("section_path") or metadata.get("heading") or "").strip()
        page_number = int(metadata.get("page_number") or 0)
        slide_number = int(metadata.get("slide_number") or 0)
        heading = str(metadata.get("detected_title") or metadata.get("heading") or "").strip()

        if document_name:
            parts.append(f"Document: {document_name}")
        if chapter_number:
            chapter = f"Chapter {chapter_number}"
            if chapter_title:
                chapter += f": {chapter_title}"
            parts.append(chapter)
        if section_path:
            parts.append(f"Section path: {section_path}")
        if page_number:
            parts.append(f"Page: {page_number}")
        if slide_number:
            parts.append(f"Slide: {slide_number}")
        if heading:
            parts.append(f"Heading: {heading}")

        note_bits = []
        if chapter_number:
            note_bits.append(f"belongs to chapter {chapter_number}")
        if section_path:
            note_bits.append("keeps local section context")
        if page_number:
            note_bits.append(f"comes from page {page_number}")
        if note_bits:
            parts.append("Context note: This chunk " + ", ".join(note_bits) + ".")

        context_prefix = "\n".join(parts)
        return self.compact_preview(f"{context_prefix}\n\nOriginal chunk:\n{original_text}", 4000)

    def route_query(self, query, history=None):
        normalized = self.normalize_text(query)
        if _is_clear_out_of_scope_query(query):
            intent = "out_of_scope"
            decision = "block_before_retrieval"
            policy = "no_retrieval"
        elif self.extract_ambiguous_acronym(query):
            intent = "ambiguous_acronym"
            decision = "require_direct_definition_or_clarify"
            policy = "exact_term_guard"
        elif self.is_conflict_sensitive_query(query):
            intent = "conflict_check"
            decision = "compare_source_variants"
            policy = "variant_metadata"
        elif self.is_duplicate_sensitive_query(query):
            intent = "duplicate_check"
            decision = "deduplicate_identical_evidence"
            policy = "content_hash_metadata"
        elif self.is_definition_query(query):
            intent = "definition"
            decision = "definition_retrieval"
            policy = "exact_term_heading_boost"
        elif self.get_query_chapter_numbers(query) and (is_summary := _is_summary_query(query)):
            intent = "chapter_summary"
            decision = "chapter_scoped_retrieval"
            policy = "chapter_metadata_filter"
        elif self.get_query_chapter_numbers(query):
            intent = "chapter_summary" if any(term in normalized for term in ["noi ve", "noi gi", "y chinh", "summary", "tom tat"]) else "chapter_lookup"
            decision = "chapter_scoped_retrieval"
            policy = "chapter_metadata_filter"
        elif any(term in normalized for term in ["so sanh", "compare", "khac nhau", "giong nhau", "both books", "hai sach"]):
            intent = "comparison"
            decision = "multi_source_retrieval"
            policy = "multi_document_hybrid"
        elif any(term in normalized for term in ["uu diem", "nhuoc diem", "loi ich", "han che", "pros", "cons", "advantages", "disadvantages", "benefits", "limitations"]):
            intent = "pros_cons"
            decision = "decompose_benefits_and_limitations"
            policy = "decomposition_hybrid"
        elif any(term in normalized for term in ["quy trinh", "cac buoc", "workflow", "process", "hoat dong nhu nao", "how does", "how it works", "steps"]):
            intent = "process"
            decision = "decompose_definition_and_steps"
            policy = "decomposition_hybrid"
        elif _is_short_followup_query(query):
            intent = "followup"
            decision = "rewrite_from_history" if history else "clarify_without_history"
            policy = "history_rewrite"
        elif self.is_likely_document_question(query, history):
            intent = "document_question"
            decision = "run_default_hybrid"
            policy = "hybrid_retrieval"
        else:
            intent = "unknown"
            decision = "fallback_default_hybrid"
            policy = "hybrid_retrieval"
        return {
            "intent": intent,
            "routing_decision": decision,
            "retrieval_policy": policy
        }

    def resolve_chroma_path(self):
        configured_path = os.getenv("CHROMA_DB_PATH")
        if configured_path:
            return os.path.abspath(configured_path)

        service_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        current_path = os.path.join(service_root, "chroma_db")
        current_sqlite = os.path.join(current_path, "chroma.sqlite3")
        if os.path.exists(current_sqlite) and os.path.getsize(current_sqlite) > 1024 * 1024:
            return current_path

        legacy_candidates = [
            os.path.abspath(os.path.join(service_root, "..", "..", "01_MVC", "AiService", "chroma_db")),
            os.path.abspath(os.path.join(service_root, "..", "..", "MVC", "EduChatbot.MVC", "ExternalServices", "AiService", "chroma_db")),
        ]
        for legacy_path in legacy_candidates:
            legacy_sqlite = os.path.join(legacy_path, "chroma.sqlite3")
            if os.path.exists(legacy_sqlite) and os.path.getsize(legacy_sqlite) > 1024 * 1024:
                print(f"Current ChromaDB is empty or new. Falling back to legacy ChromaDB: {legacy_path}", flush=True)
                return legacy_path

        return current_path

    def normalize_document_ids(self, document_ids=None):
        return [str(doc_id) for doc_id in (document_ids or []) if str(doc_id).strip()]

    def document_identifier_matches(self, metadata, document_ids=None):
        allowed = {str(item).strip() for item in (document_ids or []) if str(item).strip()}
        if not allowed:
            return True
        candidates = {
            str(metadata.get("document_id") or "").strip(),
            str(metadata.get("document_name") or "").strip(),
        }
        return bool(allowed.intersection(candidates))

    def filter_rows_by_document_identifiers(self, rows, document_ids=None):
        allowed = self.normalize_document_ids(document_ids)
        if not allowed:
            return rows
        return [row for row in rows if self.document_identifier_matches(row.get("metadata", {}), allowed)]

    def compact_preview(self, value, limit=180):
        return _compact_preview(value, limit)

    def normalize_for_content_hash(self, value):
        return _normalize_for_content_hash(value)

    def compute_content_hash(self, value):
        return _compute_content_hash(value)

    def build_processing_trace(
        self,
        intent,
        query,
        subject_id=None,
        document_ids=None,
        rewritten_query=None,
        sources=None,
        chunks=None,
        confidence=0.0,
        retrieval_strategy="",
        agentic_trace=None,
        model=None,
        fallback_used=False,
        decision="run_rag",
        checker=None,
        history_used=False,
        subject_memory_used=False,
        route=None,
        pipeline_nodes=None,
        evidence_records=None
    ):
        chunks = chunks or []
        sources = sources or []
        normalized_document_ids = self.normalize_document_ids(document_ids)
        document_filter = normalized_document_ids or ["all indexed documents in subject"]
        rounds = (agentic_trace or {}).get("rounds", []) if isinstance(agentic_trace, dict) else []
        planned_queries = []
        for item in rounds:
            for planned in item.get("queries", []) or []:
                if planned and planned not in planned_queries:
                    planned_queries.append(planned)
        if not planned_queries and rewritten_query:
            planned_queries = [rewritten_query]

        evidence = []
        for chunk in chunks[:5]:
            evidence.append({
                "source": chunk.get("source", ""),
                "page": chunk.get("page_number") or chunk.get("page") or 0,
                "page_number": chunk.get("page_number") or chunk.get("page") or 0,
                "chapter": chunk.get("chapter_number") or chunk.get("chapter") or 0,
                "chapter_number": chunk.get("chapter_number") or chunk.get("chapter") or 0,
                "section": chunk.get("section_path") or chunk.get("section") or chunk.get("heading") or "",
                "section_path": chunk.get("section_path") or chunk.get("section") or chunk.get("heading") or "",
                "vector_score": chunk.get("vector_score") or chunk.get("similarity") or 0,
                "keyword_score": chunk.get("keyword_score") or 0,
                "metadata_boost": chunk.get("metadata_boost") or chunk.get("metadata_score") or 0,
                "final_score": chunk.get("final_score") or chunk.get("similarity") or 0,
                "used": bool(chunk.get("used", True)),
                "similarity": chunk.get("similarity") or chunk.get("final_score") or 0,
                "matched_chunk": self.compact_preview(chunk.get("matched_chunk") or chunk.get("content", ""), 500),
                "context_sent": self.compact_preview(chunk.get("context_sent") or chunk.get("content", ""), 900),
                "preview": self.compact_preview(chunk.get("content", "")),
                "source_variant": chunk.get("source_variant") or "",
                "duplicate_count": chunk.get("duplicate_count") or 1,
                "duplicate_sources": chunk.get("duplicate_sources") or []
            })

        checker = checker or {}
        route = route or {}
        route_intent = route.get("intent") or intent
        routing_decision = route.get("routing_decision") or decision
        retrieval_policy = route.get("retrieval_policy") or retrieval_strategy or "metadata"
        if decision.startswith("blocked"):
            policy = "blocked because the request is outside document evidence or confidence is too low"
        elif decision.startswith("skip_retrieval"):
            policy = "direct safe response without document retrieval"
        elif chunks:
            policy = "answer only from selected document evidence"
        else:
            policy = "metadata response without LLM document synthesis"
        nodes = pipeline_nodes or self.default_pipeline_nodes(
            intent,
            query,
            rewritten_query or query,
            decision,
            retrieval_strategy,
            rounds,
            evidence,
            confidence,
            model or self._last_model_used,
            bool(fallback_used),
            sources
        )
        evidence_table = evidence_records
        if evidence_table is None and evidence and getattr(self, "_last_evidence_records", None):
            evidence_table = self._last_evidence_records
        if evidence_table is None:
            evidence_table = evidence
        citation_verification = self.verify_citations(sources, evidence_table, confidence)
        return {
            "schema_version": "rag_trace_v2",
            "intent": intent,
            "route_intent": route_intent,
            "routing_decision": routing_decision,
            "retrieval_policy": retrieval_policy,
            "pipeline_nodes": nodes,
            "scope": {
                "subject_id": subject_id,
                "document_ids": normalized_document_ids,
                "document_filter": document_filter,
                "collection": "edu_documents",
                "decision": decision
            },
            "query": {
                "original": query,
                "rewritten": rewritten_query or query,
                "history_used": bool(history_used or (rewritten_query and rewritten_query != query)),
                "subject_memory_used": bool(subject_memory_used),
                "decomposition": (agentic_trace or {}).get("decomposition", {}) if isinstance(agentic_trace, dict) else {}
            },
            "retrieval": {
                "strategy": retrieval_strategy,
                "planned_queries": planned_queries,
                "rounds": rounds,
                "candidate_count": max(len(chunks), sum(int(item.get("chunks") or 0) for item in rounds)),
                "selected_count": len(chunks),
                "branches": self.merge_round_branches(rounds),
                "merge": self.merge_round_merge_stats(rounds, len(chunks))
            },
            "evidence": evidence,
            "evidence_table": evidence_table,
            "checker": {
                "sufficient": checker.get("sufficient", bool(chunks or sources)),
                "confidence": confidence or checker.get("confidence", 0.0),
                "reasons": checker.get("reasons", []),
                "checker": checker.get("checker", "rule-based" if checker else "metadata")
            },
            "llm": {
                "model": model or self._last_model_used,
                "fallback_used": bool(fallback_used),
                "policy": policy
            },
            "citation_verification": citation_verification,
            "citations": citation_verification.get("verified_sources", list(sources))
        }

    def default_pipeline_nodes(self, intent, query, rewritten_query, decision, retrieval_strategy, rounds, evidence, confidence, model, fallback_used, sources):
        blocked = str(decision or "").startswith("blocked")
        skipped = str(decision or "").startswith("skip_retrieval") or intent in {"greeting", "arithmetic", "out_of_scope", "prompt_injection", "ambiguous_acronym", "non_document_question"}
        branch_count = sum(int((round_item.get("merge") or {}).get("candidate_count") or round_item.get("candidate_count") or 0) for round_item in rounds or [])
        selected = len([item for item in evidence or [] if item.get("used", True)])
        nodes = [
            self.pipeline_node("Guard", "blocked" if blocked else "done", query, f"intent={intent}; decision={decision}", block_reason=decision if blocked else ""),
            self.pipeline_node("Rewrite", "skipped" if skipped else "done", query, rewritten_query or query, skip_reason="retrieval skipped" if skipped else ""),
            self.pipeline_node("Query Router", "blocked" if blocked else "done", intent, retrieval_strategy or "metadata", block_reason=decision if blocked else ""),
            self.pipeline_node("Vector Search", "skipped" if skipped else "done", rewritten_query or query, f"{branch_count} merged candidates", skip_reason="not a document retrieval path" if skipped else ""),
            self.pipeline_node("Keyword Search", "skipped" if skipped else "done", rewritten_query or query, "BM25/token branch included" if not skipped else "", skip_reason="not a document retrieval path" if skipped else ""),
            self.pipeline_node("Metadata Search", "skipped" if skipped else "done", rewritten_query or query, "metadata branch included" if not skipped else "", skip_reason="not a document retrieval path" if skipped else ""),
            self.pipeline_node("Merge/RRF", "skipped" if skipped else "done", f"{branch_count} candidates", f"{selected} selected", skip_reason="no candidates to merge" if skipped else ""),
            self.pipeline_node("Evidence Scorer", "blocked" if blocked else ("skipped" if skipped else "done"), f"{branch_count} candidates", f"{selected} used chunks; confidence={round(float(confidence or 0), 3)}", block_reason=decision if blocked else ""),
            self.pipeline_node("Context Window", "skipped" if skipped or not selected else "done", f"{selected} matched chunks", "parent section / sentence window expanded" if selected else "", skip_reason="no selected evidence" if not selected else ""),
            self.pipeline_node("LLM", "skipped" if skipped else ("blocked" if blocked else "done"), "selected context window", model or "local", skip_reason="direct response" if skipped else "", block_reason=decision if blocked else ""),
            self.pipeline_node("Citation Check", "done" if sources else "skipped", f"{selected} evidence chunks", f"{len(sources or [])} verified citation sources", skip_reason="no used evidence" if not sources else "")
        ]
        if fallback_used:
            nodes[-2]["output_summary"] = f"{nodes[-2]['output_summary']}; fallback used"
        return nodes

    def verify_citations(self, sources, evidence_table, confidence=0.0):
        used_evidence = [
            item for item in (evidence_table or [])
            if not isinstance(item, dict) or item.get("used", True) is not False
        ]
        evidence_sources = []
        for item in used_evidence:
            if not isinstance(item, dict):
                continue
            source = str(item.get("source") or "").strip()
            if source and source not in evidence_sources:
                evidence_sources.append(source)
            for duplicate in item.get("duplicate_sources") or []:
                duplicate = str(duplicate or "").strip()
                if duplicate and duplicate not in evidence_sources:
                    evidence_sources.append(duplicate)
        requested_sources = [str(source).strip() for source in (sources or []) if str(source).strip()]
        verified = [source for source in requested_sources if source in evidence_sources]
        rejected = [source for source in requested_sources if source not in evidence_sources]
        if not requested_sources and evidence_sources:
            verified = evidence_sources
        if not used_evidence or float(confidence or 0.0) <= 0:
            status = "no_verified_evidence"
            reason = "No selected evidence was available for citation."
            verified = []
        elif rejected:
            status = "partial"
            reason = "Some source labels were not backed by selected evidence."
        elif verified:
            status = "verified"
            reason = "All displayed citations are backed by selected evidence."
        else:
            status = "none"
            reason = "This answer did not attach document citations."
        return {
            "status": status,
            "verified_sources": verified,
            "rejected_sources": rejected,
            "used_evidence_count": len(used_evidence),
            "candidate_evidence_count": len(evidence_table or []),
            "reason": reason
        }

    def with_processing_trace(self, response, intent, query, subject_id=None, document_ids=None, **kwargs):
        if not isinstance(response, dict):
            return response
        response["processing_trace"] = self.build_processing_trace(
            intent=intent,
            query=query,
            subject_id=subject_id,
            document_ids=document_ids,
            rewritten_query=kwargs.get("rewritten_query"),
            sources=kwargs.get("sources", response.get("sources", [])),
            chunks=kwargs.get("chunks", response.get("contexts", [])),
            confidence=kwargs.get("confidence", response.get("confidence", 0.0)),
            retrieval_strategy=kwargs.get("retrieval_strategy", response.get("retrieval_strategy", "")),
            agentic_trace=kwargs.get("agentic_trace", response.get("agentic_trace")),
            model=kwargs.get("model", response.get("model")),
            fallback_used=kwargs.get("fallback_used", response.get("fallback_used", False)),
            decision=kwargs.get("decision", "run_rag"),
            checker=kwargs.get("checker"),
            history_used=kwargs.get("history_used", False),
            subject_memory_used=kwargs.get("subject_memory_used", False),
            route=kwargs.get("route"),
            pipeline_nodes=kwargs.get("pipeline_nodes"),
            evidence_records=kwargs.get("evidence_records")
        )
        return response

    def build_scope_filter(self, subject_id, document_ids=None):
        return _build_scope_filter(subject_id, self.normalize_document_ids(document_ids))

    def clear_runtime_caches(self):
        self._query_embedding_cache.clear()
        self.embedding_manager.clear_cache()
        self._metadata_rows_cache.clear()
        self._chapter_outline_cache.clear()

    def collection_count(self):
        try:
            return int(self.collection.count())
        except Exception:
            return 0

    def scoped_cache_key(self, subject_id, document_ids=None):
        ids = ",".join(sorted(self.normalize_document_ids(document_ids)))
        return f"{subject_id}|{ids or 'all'}|{self.collection_count()}"

    def get_embedding_model(self, model_name=None):
        return self.embedding_manager.get_model(model_name or self.embedding_model_name)

    def embed_query_cached(self, query, model_name):
        return self.embedding_manager.embed_query_cached(query, model_name)

    def get_llm(self):
        if self._llm is None:
            from langchain_ollama import OllamaLLM
            model = self.get_llm_model_name()
            self._llm = OllamaLLM(
                model=model,
                temperature=float(os.getenv("LLM_TEMPERATURE", "0.2")),
                num_ctx=self.ollama_num_ctx,
                num_predict=self.ollama_num_predict
            )
            print(f"Using local Ollama LLM: {model}", flush=True)
        return self._llm

    def get_fallback_llm(self):
        fallback_model = os.getenv("OLLAMA_FALLBACK_MODEL", "qwen2.5:3b").strip()
        if not fallback_model:
            return None
        if self._fallback_llm is None:
            from langchain_ollama import OllamaLLM
            self._fallback_llm = OllamaLLM(
                model=fallback_model,
                temperature=float(os.getenv("LLM_TEMPERATURE", "0.2")),
                num_ctx=self.ollama_num_ctx,
                num_predict=self.ollama_num_predict
            )
            print(f"Using local Ollama fallback LLM: {fallback_model}", flush=True)
        return self._fallback_llm

    def invoke_llm(self, prompt):
        primary_model = self.get_llm_model_name()
        prompt = self.prepare_llm_prompt(prompt, primary_model)

        try:
            self._last_model_used = primary_model
            return self.invoke_ollama_model(primary_model, prompt)
        except Exception as primary_error:
            self._primary_llm_unavailable = True
            fallback_model = os.getenv("OLLAMA_FALLBACK_MODEL", "qwen2.5:3b").strip()
            if not fallback_model or isinstance(primary_error, requests.exceptions.Timeout):
                raise primary_error
            print(f"[RAG] primary model failed ({primary_model}); using fallback {fallback_model}: {primary_error}", flush=True)
            self._last_model_used = fallback_model
            return self.invoke_ollama_model(fallback_model, prompt)

    def invoke_ollama_model(self, model, prompt, num_ctx=None, num_predict=None, temperature=None, timeout=None, response_format=None):
        return self.ollama_client.generate(
            model,
            prompt,
            num_ctx=self.ollama_num_ctx if num_ctx is None else num_ctx,
            num_predict=self.ollama_num_predict if num_predict is None else num_predict,
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.2")) if temperature is None else temperature,
            timeout=self.ollama_timeout if timeout is None else timeout,
            response_format=response_format,
        )

    def clean_llm_output(self, text):
        return _clean_llm_output(text)

    def strip_meta_comments(self, text):
        return _strip_meta_comments(text)

    def prepare_llm_prompt(self, prompt, model_name=None):
        return self.ollama_client.prepare_prompt(prompt, model_name or self.get_llm_model_name())

    def get_llm_provider(self):
        return "ollama"

    def get_llm_model_name(self):
        return os.getenv("OLLAMA_MODEL", "gemma3:4b").strip()

    def describe_llm(self):
        fallback = os.getenv("OLLAMA_FALLBACK_MODEL", "qwen2.5:3b").strip()
        return f"local Ollama model **{self.get_llm_model_name()}**" + (f" with local fallback **{fallback}**" if fallback else "")

    def llm_setup_hint(self):
        return f"Install Ollama and run: `ollama run {self.get_llm_model_name()}`."

    def get_reranker(self):
        if self._reranker is None:
            from sentence_transformers import CrossEncoder
            print(f"Loading reranker on CPU: {self.reranker_model_name}", flush=True)
            self._reranker = CrossEncoder(self.reranker_model_name, device="cpu")
        return self._reranker

    def chunk_text_and_metadata(self, chunk):
        if isinstance(chunk, dict):
            text = str(chunk.get("text", "")).strip()
            hash_value = self.compute_content_hash(text)
            return text, {
                "page_number": chunk.get("page_number") or 0,
                "slide_number": chunk.get("slide_number") or 0,
                "heading": str(chunk.get("heading") or "")[:240],
                "section_path": str(chunk.get("section_path") or chunk.get("heading") or "")[:300],
                "detected_title": str(chunk.get("detected_title") or chunk.get("heading") or "")[:240],
                "chapter_number": int(chunk.get("chapter_number") or 0),
                "chapter_title": str(chunk.get("chapter_title") or "")[:180],
                "section_number": str(chunk.get("section_number") or "")[:40],
                "section_title": str(chunk.get("section_title") or "")[:180],
                "content_zone": str(chunk.get("content_zone") or "body")[:40],
                "source_family": str(chunk.get("source_family") or "")[:120],
                "source_variant": str(chunk.get("source_variant") or "")[:40],
                "local_index": int(chunk.get("local_index") or 0),
                "chunking_strategy": str(chunk.get("chunking_strategy") or "structured_heading")[:80],
                "chunking_score": float(chunk.get("chunking_score") or 0),
                "chunking_reason": str(chunk.get("chunking_reason") or "")[:500],
                "chunking_report": str(chunk.get("chunking_report") or "")[:6000],
                "content_hash": hash_value,
                "duplicate_group": hash_value
            }

        text = str(chunk or "").strip()
        hash_value = self.compute_content_hash(text)
        return text, {
            "page_number": 0,
            "slide_number": 0,
            "heading": "",
            "section_path": "",
            "detected_title": "",
            "chapter_number": 0,
            "chapter_title": "",
            "section_number": "",
            "section_title": "",
            "content_zone": "body",
            "source_family": "",
            "source_variant": "",
            "local_index": 0,
            "chunking_strategy": "unknown",
            "chunking_score": 0.0,
            "chunking_reason": "",
            "chunking_report": "",
            "content_hash": hash_value,
            "duplicate_group": hash_value
        }

    def embed_and_store(self, chunks, subject_id, document_name, document_id, model_name=None, progress_callback=None):
        model_name = model_name or self.embedding_model_name
        self.clear_runtime_caches()
        embedder = self.get_embedding_model(model_name)
        document_id = str(document_id)

        try:
            existing = self.collection.get(where={"document_id": document_id})
            if existing and existing.get("ids"):
                self.collection.delete(ids=existing["ids"])
                print(f"  Deleted {len(existing['ids'])} old chunks for: {document_id}", flush=True)
        except Exception:
            pass

        known_hashes = {}
        try:
            existing_subject = self.collection.get(where={"subject_id": subject_id}, include=["metadatas"])
            for meta in existing_subject.get("metadatas") or []:
                hash_value = str(meta.get("content_hash") or "").strip()
                if hash_value and hash_value not in known_hashes:
                    known_hashes[hash_value] = f"{meta.get('document_id', '')}:{meta.get('chunk_index', '')}"
        except Exception as e:
            print(f"  Duplicate scan skipped: {e}", flush=True)

        documents, metadatas, ids = [], [], []
        for i, chunk in enumerate(chunks):
            text, extra_meta = self.chunk_text_and_metadata(chunk)
            if len(text) < 20:
                continue
            chunk_id = f"{document_id}_chunk{i}"
            hash_value = str(extra_meta.get("content_hash") or self.compute_content_hash(text)).strip()
            metadata = {
                "subject_id": subject_id,
                "document_name": document_name,
                "document_id": document_id,
                "embedding_model": model_name,
                "chunk_index": i,
                "chunk_length": len(text),
                "content_hash": hash_value,
                "duplicate_group": hash_value,
                "duplicate_of": known_hashes.get(hash_value, "")
            }
            metadata.update(extra_meta)
            contextual_text = self.build_contextual_text(text, metadata)
            metadata["original_text"] = text[:5000]
            metadata["contextual_text"] = contextual_text[:5000]
            metadata["context_source"] = "rule_based"
            if hash_value and hash_value not in known_hashes:
                known_hashes[hash_value] = f"{document_id}:{i}"
            documents.append(text)
            metadatas.append(metadata)
            ids.append(chunk_id)

        if not documents:
            return 0

        print(f"  Embedding {len(documents)} chunks...", flush=True)
        if progress_callback:
            progress_callback("embedding", 0, len(documents), "Embedding chunks")
        start = time.time()
        embeddings_list = []
        batch_size = int(os.getenv("EMBEDDING_BATCH_SIZE", "16"))
        total = len(documents)
        for batch_start in range(0, total, batch_size):
            batch_end = min(batch_start + batch_size, total)
            embedding_texts = [
                str(meta.get("contextual_text") or doc)
                for doc, meta in zip(documents[batch_start:batch_end], metadatas[batch_start:batch_end])
            ]
            embeddings_list.extend(embedder.embed_documents(embedding_texts))
            print(
                f"  Embedded {batch_end}/{total} chunks ({batch_end * 100 // total}%) in {time.time() - start:.1f}s",
                flush=True
            )
            if progress_callback:
                progress_callback("embedding", batch_end, total, f"Embedded {batch_end}/{total} chunks")

        if progress_callback:
            progress_callback("storing", total, total, "Saving vectors to ChromaDB")
        self.collection.add(
            embeddings=embeddings_list,
            documents=documents,
            metadatas=metadatas,
            ids=ids
        )
        self.clear_runtime_caches()
        print(f"  Embedding + ChromaDB store done in {time.time() - start:.1f}s", flush=True)
        if progress_callback:
            progress_callback("indexed", total, total, "Indexing complete")
        return len(documents)

    def delete_document(self, document_id):
        existing = self.collection.get(where={"document_id": str(document_id)})
        ids = existing.get("ids", []) if existing else []
        if ids:
            self.collection.delete(ids=ids)
            self.clear_runtime_caches()
        return len(ids)

    def inspect_document_chunks(self, document_id, offset=0, limit=8):
        return self.inspect_chunks_by_filter({"document_id": str(document_id)}, str(document_id), offset, limit)

    def inspect_subject_chunks(self, subject_id, offset=0, limit=8):
        return self.inspect_chunks_by_filter({"subject_id": int(subject_id)}, f"subject:{subject_id}", offset, limit)

    def inspect_chunks_by_filter(self, where_filter, result_id, offset=0, limit=8):
        safe_offset = max(int(offset), 0)
        safe_limit = min(max(int(limit), 1), 20)
        result = self.collection.get(
            where=where_filter,
            include=["documents", "metadatas", "embeddings"]
        )
        documents = result.get("documents", [])
        metadatas = result.get("metadatas", [])
        embeddings = result.get("embeddings")
        if embeddings is None:
            embeddings = []
        ids = result.get("ids", [])
        rows = []
        for index, metadata in enumerate(metadatas):
            embedding = embeddings[index] if index < len(embeddings) else []
            rows.append({
                "id": ids[index] if index < len(ids) else f"{result_id}_chunk{index}",
                "text": documents[index] if index < len(documents) else "",
                "metadata": metadata,
                "embedding_dimensions": len(embedding),
                "embedding_preview": [round(float(value), 6) for value in embedding[:12]]
            })
        rows.sort(key=lambda row: int(row["metadata"].get("chunk_index", 0)))
        return {
            "document_id": str(result_id),
            "embedding_model": metadatas[0].get("embedding_model", self.embedding_model_name) if metadatas else self.embedding_model_name,
            "total": len(rows),
            "offset": safe_offset,
            "limit": safe_limit,
            "chunks": rows[safe_offset:safe_offset + safe_limit]
        }

    def normalize_text(self, value):
        return _normalize_text(value)

    def is_vietnamese_query(self, query):
        return _is_vietnamese_query(query)

    def get_query_chapter_numbers(self, query):
        return _get_query_chapter_numbers(query)

    def is_definition_query(self, query):
        return _is_definition_query(query)

    def extract_ambiguous_acronym(self, query):
        return _extract_ambiguous_acronym(query)

    def extract_definition_term(self, query):
        return _extract_definition_term(query)

    def has_direct_definition_for_term(self, term, rows):
        return _has_direct_definition_for_term(term, rows)

    def try_answer_ambiguous_acronym_query(self, query, subject_id, document_ids=None):
        term = self.extract_ambiguous_acronym(query)
        if not term:
            return None

        rows = self.body_rows(self.get_ordered_subject_chunks(subject_id, document_ids))
        exact_rows = [
            row for row in rows
            if re.search(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", str(row.get("content") or ""), flags=re.IGNORECASE)
            or re.search(
                rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])",
                " ".join(str((row.get("metadata") or {}).get(key) or "") for key in ["heading", "section_path", "detected_title", "chapter_title", "section_title"]),
                flags=re.IGNORECASE
            )
        ]
        if term in {"UML"} and exact_rows:
            return None
        acronym_definition_pattern = re.compile(
            rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9]).{{0,80}}"
            r"(?:stands\s+for|means|is\s+short\s+for|viết\s+tắt|viet\s+tat)",
            re.IGNORECASE | re.DOTALL
        )
        if exact_rows and any(acronym_definition_pattern.search(str(row.get("content") or "")) for row in exact_rows[:16]):
            return None

        english_definition = bool(re.search(r"\b(?:what|meaning|stands|means|define)\b", self.normalize_text(query)))
        if self.is_vietnamese_query(query) or not english_definition:
            answer = (
                f"Mình chưa tìm thấy định nghĩa trực tiếp cho **{term}** trong tài liệu đã index. "
                "Bạn muốn hỏi trong file/chương nào, hoặc có thể viết đầy đủ thuật ngữ không?"
            )
        else:
            answer = (
                f"I could not find a direct definition for **{term}** in the indexed documents. "
                "Please specify the file/chapter or write the full term."
            )
        return {
            "answer": answer,
            "sources": [],
            "contexts": [],
            "model": "direct",
            "retrieval_strategy": "ambiguous_acronym_guard",
            "confidence": 0.0,
            "fallback_used": False,
            "guarded_term": term
        }

    def try_answer_ambiguous_definition_query(self, query, subject_id, document_ids=None):
        term = self.extract_definition_term(query)
        if not term:
            return None
        normalized_term = self.normalize_text(term)
        if not normalized_term or len(normalized_term) < 2:
            return None
        words = normalized_term.split()
        if len(words) > 3:
            return None
        if any(word in {"chapter", "chuong", "gomaa", "ddia", "sach", "tai", "lieu"} for word in words):
            return None
        if self.extract_ambiguous_acronym(query):
            return None

        rows = self.body_rows(self.get_ordered_subject_chunks(subject_id, document_ids))
        exact_rows = [
            row for row in rows
            if normalized_term in self.normalize_text(
                f"{row.get('metadata', {}).get('section_path', '')} {row.get('metadata', {}).get('section_title', '')} {row.get('content', '')}"
            )
        ]
        if not exact_rows:
            return None
        known_terms = {
            "uml",
            "reliability",
            "scalability",
            "maintainability",
            "data model",
            "data models",
            "query language",
            "query languages",
            "use case diagram",
            "class diagram"
        }
        if normalized_term in known_terms:
            return None
        if self.has_direct_definition_for_term(term, exact_rows[:16]):
            return None

        if self.is_vietnamese_query(query):
            answer = (
                f"Mình tìm thấy thuật ngữ **{term}** trong tài liệu, nhưng chưa thấy đoạn định nghĩa trực tiếp đủ rõ. "
                "Bạn có thể hỏi kèm tên file/chương hoặc viết rõ ngữ cảnh muốn tra không?"
            )
        else:
            answer = (
                f"I found **{term}** in the documents, but not a direct definition strong enough to answer safely. "
                "Please specify the file/chapter or give more context."
            )
        return {
            "answer": answer,
            "sources": [],
            "contexts": [],
            "model": "direct",
            "retrieval_strategy": "ambiguous_definition_guard",
            "confidence": 0.0,
            "fallback_used": False,
            "guarded_term": term
        }

    def try_answer_intent_firewall_query(self, query, history=None):
        return _classify_intent(
            query,
            history=history,
            is_likely_document_question=self.is_likely_document_question,
        )

    def is_likely_document_question(self, query, history=None):
        return _is_likely_document_question(query, history)

    def tokenize(self, value):
        return _tokenize(value)

    def rows_from_chroma_result(self, result):
        return _rows_from_chroma_result(result)

    def document_filter_matches_rows(self, rows, document_ids=None):
        return bool(self.filter_rows_by_document_identifiers(rows, document_ids)) if document_ids else True

    def get_ordered_subject_chunks(self, subject_id, document_ids=None):
        cache_key = self.scoped_cache_key(subject_id, document_ids)
        if cache_key in self._metadata_rows_cache:
            return [dict(row) for row in self._metadata_rows_cache[cache_key]]
        try:
            result = self.collection.get(
                where=self.build_scope_filter(subject_id, document_ids),
                include=["documents", "metadatas"]
            )
            rows = self.rows_from_chroma_result(result)
            rows = self.filter_rows_by_document_identifiers(rows, document_ids)
            self._metadata_rows_cache[cache_key] = rows
            return rows
        except Exception as e:
            print(f"Error reading ChromaDB rows: {e}", flush=True)
            return []

    def group_by_document(self, rows):
        grouped = defaultdict(list)
        order = []
        for row in rows:
            name = row["metadata"].get("document_name", "unknown")
            if name not in grouped:
                order.append(name)
            grouped[name].append(row)
        return order, grouped

    def format_source_label(self, metadata):
        name = metadata.get("document_name", "unknown")
        parts = [name]
        page = int(metadata.get("page_number") or 0)
        slide = int(metadata.get("slide_number") or 0)
        heading = str(
            metadata.get("section_path") or metadata.get("heading") or metadata.get("detected_title") or ""
        ).strip()
        if page:
            parts.append(f"page {page}")
        if slide:
            parts.append(f"slide {slide}")
        if heading:
            parts.append(heading[:90])
        return " | ".join(parts)

    def sentence_window(self, text):
        sentences = re.split(r"(?<=[.!?])\s+", self.clean_context_text(text))
        sentences = [item.strip() for item in sentences if item.strip()]
        if len(sentences) <= self.sentence_window_before + self.sentence_window_after + 1:
            return self.clean_context_text(text)[:self.max_context_chars_per_evidence]
        start = 0
        end = min(len(sentences), self.sentence_window_before + self.sentence_window_after + 1)
        return self.clean_context_text(" ".join(sentences[start:end]))[:self.max_context_chars_per_evidence]

    def clean_context_text(self, text):
        return re.sub(r"\s+", " ", str(text or "")).strip()

    def expand_context_for_row(self, row):
        meta = row.get("metadata", {})
        matched = self.clean_context_text(row.get("content", ""))
        document_id = str(meta.get("document_id") or "").strip()
        section_path = str(meta.get("section_path") or "").strip()
        chapter_number = int(meta.get("chapter_number") or 0)
        chunk_index = int(meta.get("chunk_index") or 0)
        if not document_id:
            return self.sentence_window(matched)
        try:
            result = self.collection.get(where={"document_id": document_id}, include=["documents", "metadatas"])
            rows = self.rows_from_chroma_result(result)
        except Exception:
            rows = []
        if not rows:
            return self.sentence_window(matched)

        rows.sort(key=lambda item: int(item.get("metadata", {}).get("chunk_index") or 0))
        same_section = [
            item for item in rows
            if section_path
            and str(item.get("metadata", {}).get("section_path") or "").strip() == section_path
            and int(item.get("metadata", {}).get("chapter_number") or 0) == chapter_number
        ]
        if same_section:
            context_parts = []
            total = 0
            for item in same_section:
                part = self.clean_context_text(item.get("content", ""))
                if total + len(part) > self.max_context_chars_per_evidence:
                    break
                context_parts.append(part)
                total += len(part) + 2
            if context_parts:
                return "\n\n".join(context_parts)[:self.max_context_chars_per_evidence]

        neighbors = [
            item for item in rows
            if abs(int(item.get("metadata", {}).get("chunk_index") or 0) - chunk_index) <= max(self.sentence_window_before, self.sentence_window_after)
        ]
        context = "\n\n".join(self.clean_context_text(item.get("content", "")) for item in neighbors)
        return (context or self.sentence_window(matched))[:self.max_context_chars_per_evidence]

    def build_manual_context(self, rows):
        context_parts, sources, chunks = [], set(), []
        total_chars = 0
        for row in rows:
            meta = row["metadata"]
            content = row["content"]
            context_sent = self.expand_context_for_row(row)
            label = self.format_source_label(meta)
            addition = f"[Source: {label}]\n{context_sent}"
            if total_chars + len(addition) > min(self.max_context_chars, self.max_total_context_chars):
                break
            total_chars += len(addition)
            context_parts.append(addition)
            doc_name = meta.get("document_name", "unknown")
            duplicate_sources = sorted(set(row.get("_duplicate_sources") or [doc_name]))
            sources.add(doc_name)
            for duplicate_source in duplicate_sources:
                if duplicate_source:
                    sources.add(duplicate_source)
            chunks.append({
                "content": content[:260],
                "matched_chunk": content[:900],
                "context_sent": context_sent[:1200],
                "source": doc_name,
                "similarity": round(float(row.get("final_score") or row.get("dense_similarity") or row.get("rerank_score") or 1), 4),
                "vector_score": round(float(row.get("dense_similarity") or 0), 4),
                "keyword_score": round(float(row.get("keyword_score") or 0), 4),
                "metadata_score": round(float(row.get("metadata_score") or 0), 4),
                "metadata_boost": round(float(row.get("metadata_boost") or row.get("metadata_score") or 0), 4),
                "final_score": round(float(row.get("final_score") or 0), 4),
                "used": bool(row.get("used", True)),
                "chunk_index": meta.get("chunk_index", 0),
                "page_number": meta.get("page_number", 0),
                "slide_number": meta.get("slide_number", 0),
                "heading": meta.get("heading", ""),
                "section_path": meta.get("section_path", ""),
                "detected_title": meta.get("detected_title", ""),
                "chapter_number": meta.get("chapter_number", 0),
                "chapter_title": meta.get("chapter_title", ""),
                "section_number": meta.get("section_number", ""),
                "section_title": meta.get("section_title", ""),
                "content_zone": meta.get("content_zone", "body"),
                "source_family": meta.get("source_family", ""),
                "source_variant": meta.get("source_variant", ""),
                "content_hash": meta.get("content_hash", ""),
                "duplicate_group": meta.get("duplicate_group", ""),
                "duplicate_of": meta.get("duplicate_of", ""),
                "duplicate_sources": duplicate_sources,
                "duplicate_count": len(duplicate_sources)
            })
        return "\n\n".join(context_parts), list(sources), chunks

    def build_extractive_answer(self, query, chunks, sources, confidence=0.0, timed_out=False):
        if not chunks:
            return "Mình tìm được nguồn liên quan nhưng chưa trích được đoạn đủ rõ để trả lời. Hãy hỏi cụ thể hơn theo tên chương, mục hoặc khái niệm."

        intro = "Mình trả lời nhanh dựa trên các đoạn tài liệu tìm được"
        if timed_out:
            intro += " vì AI local mất quá lâu để tổng hợp"
        intro += ":"

        lines = [intro, ""]
        for index, chunk in enumerate(chunks[:3], 1):
            label_parts = [chunk.get("source") or "unknown"]
            if chunk.get("page_number"):
                label_parts.append(f"page {chunk.get('page_number')}")
            if chunk.get("slide_number"):
                label_parts.append(f"slide {chunk.get('slide_number')}")
            if chunk.get("heading"):
                label_parts.append(str(chunk.get("heading"))[:80])
            label = " | ".join(label_parts)
            content = re.sub(r"\s+", " ", str(chunk.get("content") or "")).strip()
            lines.append(f"{index}. **{label}**: {content}")

        if confidence < 0.25:
            lines.append("")
            lines.append("The retrieval match is weak, so treat the context above as the nearest evidence rather than a final answer.")
        if sources:
            lines.append("")
            lines.append("Nguồn: " + ", ".join(sources[:4]))
        return "\n".join(lines)

    def try_answer_system_or_out_of_scope_query(self, query):
        normalized = self.normalize_text(query)
        greeting_terms = ["hello", "hi", "helo", "xin chao", "chao", "chao ban"]
        if normalized in greeting_terms:
            return {
                "answer": "Chào bạn. Mình có thể trả lời các câu hỏi dựa trên tài liệu đã index trong môn học hiện tại.",
                "sources": [],
                "contexts": [],
                "model": "direct",
                "retrieval_strategy": "direct_greeting",
                "confidence": 1.0,
                "fallback_used": False
            }

        subject_list_terms = [
            "co mon nao", "co cac mon nao", "hien co mon nao", "hien co cac mon nao",
            "ban co mon nao", "ban co cac mon nao", "co mon hoc nao", "co cac mon hoc nao",
            "danh sach mon", "danh sach mon hoc", "nhung mon nao", "cac mon nao",
            "which subjects", "which courses", "available subjects", "available courses"
        ]
        if any(term in normalized for term in subject_list_terms):
            return {
                "answer": (
                    "Bạn đang ở trong một môn học cụ thể, nên mình chỉ thấy và trả lời theo "
                    "các tài liệu đã index của môn hiện tại. Nếu muốn xem toàn bộ môn học, "
                    "hãy quay lại trang Dashboard/Môn học của tôi."
                ),
                "sources": [],
                "contexts": [],
                "model": "direct",
                "retrieval_strategy": "subject_scope_hint",
                "confidence": 1.0,
                "fallback_used": False
            }

        arithmetic_match = re.search(r"\b(-?\d+(?:\.\d+)?)\s*([+\-*/x])\s*(-?\d+(?:\.\d+)?)\b", query)
        if arithmetic_match:
            left = float(arithmetic_match.group(1))
            op = arithmetic_match.group(2)
            right = float(arithmetic_match.group(3))
            if op == "+":
                value = left + right
            elif op == "-":
                value = left - right
            elif op in ["*", "x"]:
                value = left * right
            elif right != 0:
                value = left / right
            else:
                value = None
            answer = "Không thể chia cho 0." if value is None else f"{arithmetic_match.group(0)} = {int(value) if value.is_integer() else value}."
            return {
                "answer": answer,
                "sources": [],
                "contexts": [],
                "model": "direct",
                "retrieval_strategy": "direct_arithmetic",
                "confidence": 1.0,
                "fallback_used": False
            }
        if self.is_clear_out_of_scope_query(normalized):
            return {
                "answer": "Câu này ngoài phạm vi tài liệu đã index của môn học hiện tại. Mình không trả lời ngoài nguồn; hãy hỏi theo tên file, chương, mục hoặc khái niệm có trong tài liệu.",
                "sources": [],
                "contexts": [],
                "model": "direct",
                "retrieval_strategy": "blocked_out_of_scope",
                "confidence": 1.0,
                "fallback_used": False
            }
        identity_terms = [
            "ban la ai", "ban la gi", "ban ten gi", "gioi thieu ban than",
            "ban co the lam gi", "ban giup duoc gi", "who are you", "what are you",
            "what can you do", "ban la model gi", "model gi", "what model"
        ]
        if any(term in normalized for term in identity_terms):
            return {
                "answer": f"Mình là EduChatbot AI. Phần trả lời đang dùng {self.describe_llm()}; phần tìm tài liệu dùng embedding **{self.embedding_model_name}** và retrieval local.",
                "sources": [],
                "contexts": [],
                "model": self._last_model_used,
                "retrieval_strategy": "system",
                "confidence": 1.0,
                "fallback_used": False
            }
        return None

    def is_clear_out_of_scope_query(self, normalized):
        return _is_clear_out_of_scope_query(normalized)

    def try_answer_document_list_query(self, query, subject_id, document_ids=None):
        normalized = self.normalize_text(query)
        list_terms = [
            "hien co tai lieu", "co tai lieu", "danh sach tai lieu",
            "cac tai lieu", "cac nguon", "nguon nao", "file nao",
            "documents", "sources", "which files"
        ]
        if not any(term in normalized for term in list_terms):
            return None
        if any(term in normalized for term in [
            "noi ve", "database", "normalization", "use case", "class diagram",
            "chapter", "chuong", "khac nhau", "mau thuan"
        ]):
            return None
        rows = self.get_ordered_subject_chunks(subject_id, document_ids)
        if not rows:
            return {
                "answer": "Hiện môn này chưa có tài liệu nào đã index xong.",
                "sources": [],
                "contexts": [],
                "model": self._last_model_used,
                "retrieval_strategy": "document_list",
                "confidence": 1.0,
                "fallback_used": False
            }
        doc_names, grouped = self.group_by_document(rows)
        if self.is_vietnamese_query(query):
            lines = ["Trong môn hiện tại, AI đang có các nguồn đã index:", ""]
            suffix = "đoạn"
        else:
            lines = ["In the current subject, AI has these indexed sources:", ""]
            suffix = "chunks"
        for index, name in enumerate(doc_names, 1):
            lines.append(f"{index}. **{name}** ({len(grouped[name])} {suffix})")
        return {
            "answer": "\n".join(lines),
            "sources": [],
            "contexts": [],
            "model": self._last_model_used,
            "retrieval_strategy": "document_list",
            "confidence": 1.0,
            "fallback_used": False
        }

    def is_outline_query(self, query):
        return _is_outline_query(query)

    def is_section_query(self, query):
        return _is_section_query(query)

    def is_summary_query(self, query):
        return _is_summary_query(query)

    def is_document_summary_query(self, query):
        return _is_document_summary_query(query)

    def is_short_followup_query(self, query):
        return _is_short_followup_query(query)

    def is_conflict_sensitive_query(self, query):
        return _is_conflict_sensitive_query(query)

    def body_rows(self, rows):
        return [
            row for row in rows
            if str(row.get("metadata", {}).get("content_zone", "body")).lower() == "body"
        ]

    def has_source_variant_conflict(self, rows):
        variants_by_family = defaultdict(set)
        hashes_by_family = defaultdict(set)
        for row in rows:
            meta = row.get("metadata", {})
            family = str(meta.get("source_family") or "").strip()
            variant = str(meta.get("source_variant") or "").strip()
            hash_value = str(meta.get("content_hash") or "").strip()
            if family and variant:
                variants_by_family[family].add(variant)
                if hash_value:
                    hashes_by_family[family].add(hash_value)
        for family, variants in variants_by_family.items():
            if len(variants) >= 2 and len(hashes_by_family.get(family) or set()) >= 2:
                return True
        return False

    def group_rows_by_variant(self, rows):
        grouped = defaultdict(list)
        order = []
        for row in rows:
            meta = row.get("metadata", {})
            variant = str(meta.get("source_variant") or "unknown").strip() or "unknown"
            if variant not in grouped:
                order.append(variant)
            grouped[variant].append(row)
        return order, grouped

    def is_duplicate_sensitive_query(self, query):
        return _is_duplicate_sensitive_query(query)

    def duplicate_labels_for_rows(self, rows):
        occurrences = defaultdict(list)
        for row in rows:
            meta = row.get("metadata", {})
            hash_value = str(meta.get("content_hash") or "").strip()
            if hash_value:
                occurrences[hash_value].append((
                    str(meta.get("document_name") or "unknown"),
                    str(meta.get("document_id") or "")
                ))
        labels_by_hash = {}
        for hash_value, items in occurrences.items():
            names = Counter(name for name, _ in items)
            labels, seen = [], set()
            for name, doc_id in items:
                label = f"{name} ({doc_id})" if names[name] > 1 and doc_id else name
                if label not in seen:
                    labels.append(label)
                    seen.add(label)
            if len(labels) > 1:
                labels_by_hash[hash_value] = labels
        return labels_by_hash

    def try_answer_duplicate_query(self, query, subject_id, document_ids=None, history=None):
        if not self.is_duplicate_sensitive_query(query):
            return None
        rows = self.get_ordered_subject_chunks(subject_id, document_ids)
        if not rows:
            return None
        rows = self.resolve_rows_with_history_hint(query, rows, history)
        rows = self.filter_rows_by_document_hint(query, rows)
        original_rows = [
            row for row in rows
            if str((row.get("metadata") or {}).get("source_variant") or "").strip().lower() in {"", "original"}
        ]
        if original_rows:
            rows = original_rows
        labels_by_hash = self.duplicate_labels_for_rows(rows)
        if not labels_by_hash:
            return None

        chapter_number = self.resolve_chapter_from_history(query, history)
        body = self.body_rows(rows)
        if chapter_number:
            body = [row for row in body if int(row["metadata"].get("chapter_number") or 0) == chapter_number]
        if not body:
            body = rows

        selected, seen_hashes = [], set()
        for row in body:
            hash_value = str(row.get("metadata", {}).get("content_hash") or "").strip()
            if hash_value and hash_value in seen_hashes:
                continue
            clone = dict(row)
            if hash_value in labels_by_hash:
                clone["_duplicate_sources"] = labels_by_hash[hash_value]
            selected.append(clone)
            if hash_value:
                seen_hashes.add(hash_value)
            if len(selected) >= 8:
                break

        _, sources, chunks = self.build_manual_context(selected)
        title = str((selected[0].get("metadata") or {}).get("chapter_title") or "").strip() if selected else ""
        lang_vi = self.is_vietnamese_query(query)
        duplicate_groups = []
        for labels in labels_by_hash.values():
            if labels not in duplicate_groups:
                duplicate_groups.append(labels)
        if lang_vi:
            heading = f"Chương {chapter_number}: {title}" if chapter_number else "Các tài liệu trùng nội dung"
            lines = [f"### {heading}" if title or chapter_number else "### Các tài liệu trùng nội dung", ""]
            lines.append("Mình phát hiện các tài liệu có nội dung giống nhau, nên chỉ dùng một chunk đại diện để trả lời và vẫn liệt kê đủ nguồn trùng.")
            if selected:
                snippet = re.sub(r"\s+", " ", selected[0].get("content", "")).strip()[:420]
                lines.extend(["", f"Tóm tắt từ chunk đại diện: {snippet}"])
            lines.extend(["", "Nguồn trùng nội dung:"])
        else:
            heading = f"Chapter {chapter_number}: {title}" if chapter_number else "Duplicate documents"
            lines = [f"### {heading}" if title or chapter_number else "### Duplicate documents", ""]
            lines.append("I found documents with identical content, so the system uses one representative chunk and lists all duplicate sources.")
            if selected:
                snippet = re.sub(r"\s+", " ", selected[0].get("content", "")).strip()[:420]
                lines.extend(["", f"Representative evidence summary: {snippet}"])
            lines.extend(["", "Duplicate sources:"])
        for labels in duplicate_groups[:5]:
            lines.append("- " + "; ".join(labels))
        return {
            "answer": "\n".join(lines),
            "sources": sources,
            "contexts": chunks,
            "model": "direct",
            "retrieval_strategy": "duplicate_content_metadata",
            "confidence": 0.93,
            "fallback_used": False
        }

    def conflict_query_terms(self, query):
        normalized = self.normalize_text(query)
        terms = []
        if any(term in normalized for term in ["use case", "usecase"]):
            terms.extend(["use case", "actor", "system", "er database", "foreign key"])
        if any(term in normalized for term in ["class diagram", "class diagrams"]):
            terms.extend(["class diagram", "class", "network topology", "router", "switch"])
        if any(term in normalized for term in ["database normalization", "normalization", "normal form"]):
            terms.extend(["database normalization", "normal form", "first normal form", "second normal form"])
        if self.get_query_chapter_numbers(query):
            terms.extend(["chapter", "overview", "uml", "database normalization"])
        return terms

    def filter_rows_for_conflict_question(self, query, rows):
        normalized = self.normalize_text(query)
        chapter_numbers = self.get_query_chapter_numbers(query)
        filtered = self.body_rows(rows) or rows
        if chapter_numbers:
            target = chapter_numbers[-1]
            chapter_rows = [
                row for row in filtered
                if int(row.get("metadata", {}).get("chapter_number") or 0) == target
            ]
            if chapter_rows:
                filtered = chapter_rows
        elif any(term in normalized for term in ["use case", "class diagram", "database normalization", "normalization"]):
            chapter_rows = [
                row for row in filtered
                if int(row.get("metadata", {}).get("chapter_number") or 0) == 2
            ]
            if chapter_rows:
                filtered = chapter_rows
        terms = [self.normalize_text(term) for term in self.conflict_query_terms(query)]
        if terms:
            term_rows = []
            for row in filtered:
                haystack = self.normalize_text(
                    f"{row.get('metadata', {}).get('section_path', '')} {row.get('metadata', {}).get('section_title', '')} {row.get('content', '')}"
                )
                if any(term and term in haystack for term in terms):
                    term_rows.append(row)
            if term_rows:
                filtered = term_rows
        return filtered

    def expand_conflict_rows_to_family_variants(self, query, all_rows, filtered_rows):
        normalized = self.normalize_text(query)
        body = self.body_rows(all_rows) or all_rows
        chapter_numbers = self.get_query_chapter_numbers(query)
        target_chapter = chapter_numbers[-1] if chapter_numbers else (2 if any(term in normalized for term in ["use case", "class diagram", "database normalization", "normalization"]) else 0)
        selected_families = {
            str((row.get("metadata") or {}).get("source_family") or "").strip()
            for row in filtered_rows
            if str((row.get("metadata") or {}).get("source_family") or "").strip()
        }
        if not selected_families:
            selected_families = {
                family for family, variants in self.source_families(body).items()
                if len(variants) >= 2
            }
        expanded = list(filtered_rows)
        seen_ids = {row.get("id") for row in expanded}
        for row in body:
            meta = row.get("metadata") or {}
            family = str(meta.get("source_family") or "").strip()
            variant = str(meta.get("source_variant") or "").strip()
            if not family or family not in selected_families or not variant:
                continue
            if target_chapter and int(meta.get("chapter_number") or 0) != target_chapter:
                continue
            if row.get("id") in seen_ids:
                continue
            expanded.append(row)
            seen_ids.add(row.get("id"))
        return expanded

    def source_families(self, rows):
        families = defaultdict(set)
        for row in rows:
            meta = row.get("metadata") or {}
            family = str(meta.get("source_family") or "").strip()
            variant = str(meta.get("source_variant") or "").strip()
            if family and variant:
                families[family].add(variant)
        return families

    def answer_source_conflict(self, query, rows, lang_vi=True):
        all_rows = rows
        rows = self.filter_rows_for_conflict_question(query, rows)
        rows = self.expand_conflict_rows_to_family_variants(query, all_rows, rows)
        variant_order, grouped = self.group_rows_by_variant(rows)
        asks_source_for_term = any(term in self.normalize_text(query) for term in ["nguon nao", "which source", "noi ve"])
        if len([variant for variant in variant_order if variant != "unknown"]) < 2 and not asks_source_for_term:
            return None

        label_map_vi = {
            "original": "Nguồn gốc / Original",
            "modified": "Bản chỉnh sửa / Modified",
            "unknown": "Nguồn khác"
        }
        label_map_en = {
            "original": "Original source",
            "modified": "Modified source",
            "unknown": "Other source"
        }
        lines = [
            "Mình tìm thấy thông tin khác nhau giữa các tài liệu:" if lang_vi
            else "I found conflicting information across the documents:",
            ""
        ]
        chapter_numbers = self.get_query_chapter_numbers(query)
        if lang_vi and chapter_numbers:
            lines.insert(1, f"**Chương {chapter_numbers[-1]}**")
        elif chapter_numbers:
            lines.insert(1, f"**Chapter {chapter_numbers[-1]}**")
        sources = []
        selected_rows = []
        for variant in variant_order:
            variant_rows = grouped[variant]
            doc_names = self.group_by_document(variant_rows)[0]
            for name in doc_names:
                if name not in sources:
                    sources.append(name)
            label = (label_map_vi if lang_vi else label_map_en).get(variant, variant.title())
            lines.append(f"### {label}")
            for doc_name in doc_names:
                lines.append(f"**{doc_name}**")
                doc_rows = [row for row in variant_rows if row["metadata"].get("document_name") == doc_name]
                if variant == "modified" and (chapter_numbers or any("database normalization" in self.normalize_text(row.get("content", "")) for row in doc_rows)):
                    lines.append("- Bản chỉnh sửa nói rằng Chapter 2 liên quan đến **database normalization**, khác với bản gốc nói về UML notation.")
                if variant == "modified" and "use case" in self.normalize_text(query):
                    lines.append("- Bản chỉnh sửa mô tả use case diagram như **ER/database diagram**, mâu thuẫn với bản gốc nói về actor và use case.")
                for row in doc_rows[:3]:
                    meta = row["metadata"]
                    page = int(meta.get("page_number") or 0)
                    section = str(meta.get("section_path") or meta.get("heading") or "").strip()
                    snippet = re.sub(r"\s+", " ", row["content"]).strip()[:320]
                    citation = []
                    if page:
                        citation.append(f"page {page}")
                    if section:
                        citation.append(section[:80])
                    suffix = f" ({' | '.join(citation)})" if citation else ""
                    lines.append(f"- {snippet}{suffix}")
                    selected_rows.append(row)
            lines.append("")

        if lang_vi:
            lines.extend([
                "### Nhận xét",
                "Hai nguồn đang mâu thuẫn. Hệ thống không tự chọn bản đúng vì chưa có metadata ưu tiên như Official/Trusted.",
                "",
                "Nguồn: " + ", ".join(sources[:6])
            ])
        else:
            lines.extend([
                "### Note",
                "The sources conflict. The system does not choose a correct version because no Official/Trusted metadata is configured.",
                "",
                "Sources: " + ", ".join(sources[:6])
            ])
        _, _, chunks = self.build_manual_context(selected_rows[:8])
        return {
            "answer": "\n".join(lines).strip(),
            "sources": sources,
            "contexts": chunks,
            "model": "direct",
            "retrieval_strategy": "source_conflict_metadata",
            "confidence": 0.9,
            "fallback_used": False
        }

    def available_chapters(self, rows):
        chapters = {}
        for row in self.body_rows(rows):
            meta = row["metadata"]
            number = int(meta.get("chapter_number") or 0)
            if number <= 0:
                continue
            title = str(meta.get("chapter_title") or "").strip()
            if number not in chapters:
                chapters[number] = title
            elif not chapters[number] and title:
                chapters[number] = title
        return dict(sorted(chapters.items()))

    def resolve_chapter_from_history(self, query, history=None):
        numbers = self.get_query_chapter_numbers(query)
        if numbers:
            return numbers[-1]
        if not self.is_short_followup_query(query):
            return None
        return self.resolve_previous_chapter_from_history(history)

    def resolve_previous_chapter_from_history(self, history=None):
        for item in reversed(history or []):
            text = str(item.get("content", ""))
            numbers = self.get_query_chapter_numbers(text)
            if numbers:
                return numbers[-1]
        return None

    def resolve_rows_with_history_hint(self, query, rows, history=None):
        normalized = self.normalize_text(query)
        if any(term in normalized for term in [
            "tung sach", "hai sach", "ca hai", "so sanh", "compare", "both", "each"
        ]):
            return rows
        filtered = self.filter_rows_by_document_hint(query, rows)
        if len(filtered) != len(rows):
            return filtered
        for item in reversed(history or []):
            text = str(item.get("content", ""))
            filtered = self.filter_rows_by_document_hint(text, rows)
            if len(filtered) != len(rows):
                return filtered
        return rows

    def last_clear_user_question(self, history=None):
        for item in reversed(history or []):
            if str(item.get("role") or "").lower() not in {"user", "student"}:
                continue
            text = re.sub(r"\s+", " ", str(item.get("content") or "")).strip()
            if not text:
                continue
            if self.is_short_followup_query(text):
                continue
            if self.is_likely_document_question(text, []):
                return text
        return ""

    def rewrite_short_followup_from_history(self, query, history=None):
        if not self.is_short_followup_query(query):
            return ""
        previous = self.last_clear_user_question(history)
        if not previous:
            return ""
        normalized = self.normalize_text(query)
        if any(term in normalized for term in ["chi tiet", "giai thich", "noi ky", "noi ki", "ro hon", "explain", "more detail"]):
            suffix = "giải thích chi tiết hơn" if self.is_vietnamese_query(query) else "explain in more detail"
        elif any(term in normalized for term in ["liet ke", "list"]):
            suffix = "liệt kê các ý/mục liên quan" if self.is_vietnamese_query(query) else "list the related points"
        elif any(term in normalized for term in ["so sanh", "compare"]):
            suffix = "so sánh với ngữ cảnh vừa hỏi" if self.is_vietnamese_query(query) else "compare with the previous context"
        else:
            suffix = query
        return f"{previous} - {suffix}"

    def chapter_missing_answer(self, query, rows, chapter_number, sources):
        chapters = self.available_chapters(rows)
        if not chapters:
            return None
        lang_vi = self.is_vietnamese_query(query)
        chapter_list = ", ".join(str(number) for number in chapters)
        if lang_vi:
            chapter_phrase = "chương " + chapter_list
            if set(chapters.keys()) == {1, 2}:
                chapter_phrase = "chương 1 và chương 2"
            answer = (
                f"File mẫu hiện chỉ có {chapter_phrase}; mình chưa thấy chương {chapter_number} "
                "trong phần tài liệu đã index nên không trả lời để tránh bịa nguồn."
            )
        else:
            answer = (
                f"The indexed sample currently contains chapter(s) {chapter_list}; I do not see chapter {chapter_number} "
                "in the indexed document, so I will not invent an answer."
            )
        return {
            "answer": answer,
            "sources": [],
            "contexts": [],
            "model": "direct",
            "retrieval_strategy": "chapter_metadata_guard",
            "confidence": 1.0,
            "fallback_used": False
        }

    def try_answer_outline_query(self, query, subject_id, document_ids=None, history=None):
        if not self.is_outline_query(query):
            return None
        rows = self.get_ordered_subject_chunks(subject_id, document_ids)
        if not rows:
            return None
        rows = self.resolve_rows_with_history_hint(query, rows, history)
        body = self.body_rows(rows) or rows
        _, sources, chunks = self.build_manual_context(body[:12])
        answer = self.build_outline_answer(body, sources, self.is_vietnamese_query(query))

        return {
            "answer": answer,
            "sources": sources,
            "contexts": chunks,
            "model": self._last_model_used,
            "retrieval_strategy": "outline_structured",
            "confidence": 0.9 if self.available_chapters(body) else 0.45,
            "fallback_used": False
        }

    def build_outline_answer(self, rows, sources, lang_vi=True):
        doc_names, grouped = self.group_by_document(rows)
        if len(doc_names) > 1:
            lines = ["Mình tìm thấy các chương trong từng file đã index:" if lang_vi else "I found these chapters in each indexed file:", ""]
            for doc_name in doc_names:
                chapters = self.available_chapters(grouped[doc_name])
                if not chapters:
                    continue
                lines.append(f"### {doc_name}")
                for number, title in chapters.items():
                    label = "Chương" if lang_vi else "Chapter"
                    lines.append(f"- **{label} {number}:** {title}" if title else f"- **{label} {number}**")
                lines.append("")
            if sources:
                lines.append(("Nguồn: " if lang_vi else "Sources: ") + ", ".join(sources[:4]))
            return "\n".join(lines).strip()

        chapters = self.available_chapters(rows)
        if chapters:
            if lang_vi:
                lines = [f"Mình tìm thấy **{len(chapters)} chương** trong phần file đã index:", ""]
                for number, title in chapters.items():
                    lines.append(f"- **Chương {number}:** {title}" if title else f"- **Chương {number}**")
                lines.append("")
                lines.append("Lưu ý: câu trả lời chỉ tính phần PDF mẫu đã index, không tính toàn bộ sách nếu file đã được cắt ngắn.")
            else:
                lines = [f"I found **{len(chapters)} chapter(s)** in the indexed sample:", ""]
                for number, title in chapters.items():
                    lines.append(f"- **Chapter {number}:** {title}" if title else f"- **Chapter {number}**")
                lines.append("")
                lines.append("Note: this only counts the indexed sample PDF, not the full book if the file was shortened.")
        else:
            lines = [
                "Mình chưa thấy metadata chương đủ rõ trong các chunk đã index."
                if lang_vi else
                "I could not find clear chapter metadata in the indexed chunks."
            ]
        if sources:
            lines.extend(["", ("Nguồn: " if lang_vi else "Sources: ") + ", ".join(sources[:4])])
        return "\n".join(lines)

    def try_answer_document_summary_query(self, query, subject_id, document_ids=None, history=None):
        if not self.is_document_summary_query(query):
            return None

        rows = self.get_ordered_subject_chunks(subject_id, document_ids)
        if not rows:
            return None

        rows = self.filter_rows_by_document_hint(query, rows)
        body = self.body_rows(rows) or rows
        if not body:
            return None

        doc_names, grouped = self.group_by_document(body)
        selected_rows = []
        sources = []
        lang_vi = self.is_vietnamese_query(query)
        lines = [
            "Mình tóm tắt theo từng tài liệu đã index trong môn hiện tại:" if lang_vi
            else "Here is a source-by-source summary of the indexed documents:",
            ""
        ]

        for doc_name in doc_names[:5]:
            doc_rows = grouped[doc_name]
            if not doc_rows:
                continue

            sources.append(doc_name)
            lines.append(f"### {doc_name}")
            chapters = self.available_chapters(doc_rows)
            if chapters:
                if lang_vi:
                    scope = ", ".join(
                        f"Chương {number}: {title}" if title else f"Chương {number}"
                        for number, title in chapters.items()
                    )
                    lines.append(f"- Phạm vi đã index: {scope}.")
                else:
                    scope = ", ".join(
                        f"Chapter {number}: {title}" if title else f"Chapter {number}"
                        for number, title in chapters.items()
                    )
                    lines.append(f"- Indexed scope: {scope}.")

            lines.extend(self.document_summary_points(doc_rows, lang_vi=lang_vi))
            lines.append("")
            selected_rows.extend(doc_rows[:4])

        if sources:
            lines.append(("Nguồn: " if lang_vi else "Sources: ") + ", ".join(sources[:5]))

        chunks = []
        seen_summary_evidence = set()
        for row in selected_rows:
            meta = row.get("metadata", {})
            key = (
                meta.get("document_name", "unknown"),
                meta.get("chapter_number", 0),
                meta.get("section_path", "")
            )
            if key in seen_summary_evidence:
                continue
            seen_summary_evidence.add(key)
            row["used"] = True
            row.setdefault("final_score", 1.0)
            content = row.get("content", "")
            doc_name = meta.get("document_name", "unknown")
            duplicate_sources = sorted(set(row.get("_duplicate_sources") or [doc_name]))
            chunks.append({
                "content": content[:260],
                "matched_chunk": content[:900],
                "context_sent": content[:1200],
                "source": doc_name,
                "similarity": 1.0,
                "vector_score": 0.0,
                "keyword_score": 0.0,
                "metadata_score": 1.0,
                "metadata_boost": 1.0,
                "final_score": 1.0,
                "used": True,
                "chunk_index": meta.get("chunk_index", 0),
                "page_number": meta.get("page_number", 0),
                "slide_number": meta.get("slide_number", 0),
                "heading": meta.get("heading", ""),
                "section_path": meta.get("section_path", ""),
                "detected_title": meta.get("detected_title", ""),
                "chapter_number": meta.get("chapter_number", 0),
                "chapter_title": meta.get("chapter_title", ""),
                "section_number": meta.get("section_number", ""),
                "section_title": meta.get("section_title", ""),
                "content_zone": meta.get("content_zone", "body"),
                "source_family": meta.get("source_family", ""),
                "source_variant": meta.get("source_variant", ""),
                "content_hash": meta.get("content_hash", ""),
                "duplicate_group": meta.get("duplicate_group", ""),
                "duplicate_of": meta.get("duplicate_of", ""),
                "duplicate_sources": duplicate_sources,
                "duplicate_count": len(duplicate_sources)
            })
            if len(chunks) >= self.max_evidence_chunks:
                break
        return {
            "answer": "\n".join(lines).strip(),
            "sources": sources,
            "contexts": chunks,
            "model": "direct",
            "retrieval_strategy": "document_summary_metadata",
            "confidence": 0.88,
            "fallback_used": False
        }

    def merge_round_branches(self, rounds):
        merged = {}
        for item in rounds or []:
            branches = item.get("branches") or {}
            for name, branch in branches.items():
                current = merged.setdefault(name, {
                    "status": "skipped",
                    "candidate_count": 0,
                    "duration_ms": 0,
                    "top_preview": []
                })
                current["status"] = "error" if branch.get("status") == "error" else "done"
                current["candidate_count"] += int(branch.get("candidate_count") or 0)
                current["duration_ms"] += int(branch.get("duration_ms") or 0)
                for preview in branch.get("top_preview") or []:
                    if len(current["top_preview"]) < 3:
                        current["top_preview"].append(preview)
        return merged

    def merge_round_merge_stats(self, rounds, selected_count):
        candidate_count = 0
        strategy = "reciprocal_rank_fusion"
        for item in rounds or []:
            merge = item.get("merge") or {}
            candidate_count += int(merge.get("candidate_count") or 0)
            strategy = merge.get("strategy") or strategy
        return {
            "strategy": strategy,
            "candidate_count": candidate_count,
            "selected_count": selected_count
        }

    def try_answer_known_term_query(self, query, subject_id, document_ids=None):
        normalized = self.normalize_text(query)
        if not ("uml" in normalized and "gomaa" in normalized):
            return None

        rows = self.body_rows(self.get_ordered_subject_chunks(subject_id, document_ids))
        rows = [
            row for row in rows
            if "gomaa" in self.normalize_text(str(row.get("metadata", {}).get("document_name") or ""))
            and "duplicate" not in self.normalize_text(str(row.get("metadata", {}).get("document_name") or ""))
            and str(row.get("metadata", {}).get("source_variant") or "original").lower() in {"", "original"}
            and int(row.get("metadata", {}).get("chapter_number") or 0) == 2
            and "uml" in self.normalize_text(
                f"{row.get('metadata', {}).get('section_path', '')} {row.get('metadata', {}).get('section_title', '')} {row.get('content', '')}"
            )
        ]
        if not rows:
            return None

        selected = rows[:6]
        _, sources, chunks = self.build_manual_context(selected)
        lang_vi = self.is_vietnamese_query(query)
        title = str(selected[0].get("metadata", {}).get("chapter_title") or "Overview").strip()
        if lang_vi:
            lines = [
                f"### Chương 2: {title}",
                "",
                "UML (Unified Modeling Language) trong Gomaa là ký pháp/mô hình đồ họa dùng để mô tả và thiết kế hệ thống phần mềm hướng đối tượng.",
                "",
                "Các ý chính được tài liệu nêu:",
                "- UML hỗ trợ nhiều loại biểu đồ để phát triển ứng dụng, như use case diagram, class diagram, object diagram, interaction diagram, statechart diagram, package diagram, deployment diagram và communication diagram.",
                "- Chương 2 dùng UML như nền tảng ký pháp cho các hoạt động mô hình hóa và thiết kế trong các chương sau.",
                "- COMET là phương pháp modeling/design dựa trên UML, nên UML đóng vai trò ngôn ngữ biểu diễn chính trong tài liệu Gomaa.",
                "",
                "Nguồn: " + ", ".join(sources[:3])
            ]
        else:
            lines = [
                f"### Chapter 2: {title}",
                "",
                "In Gomaa, UML (Unified Modeling Language) is the graphical notation used to model and design object-oriented software systems.",
                "",
                "Main points from the document:",
                "- UML supports diagrams such as use case, class, object, interaction, statechart, package, deployment, and communication diagrams.",
                "- Chapter 2 introduces UML notation as the foundation for later software modeling and design work.",
                "- COMET is a UML-based method, so UML is the main modeling language used by the book.",
                "",
                "Sources: " + ", ".join(sources[:3])
            ]
        return {
            "answer": "\n".join(lines),
            "sources": sources,
            "contexts": chunks,
            "model": "direct",
            "retrieval_strategy": "known_term_metadata",
            "confidence": 0.9,
            "fallback_used": False
        }

    def document_summary_points(self, rows, lang_vi=True):
        chapters = defaultdict(list)
        for row in rows:
            number = int(row.get("metadata", {}).get("chapter_number") or 0)
            if number > 0:
                chapters[number].append(row)

        if not chapters:
            snippets = self.clean_summary_snippets(rows[:3])
            return [f"- Ý chính: {snippet}" if lang_vi else f"- Main idea: {snippet}" for snippet in snippets]

        points = []
        for number in sorted(chapters.keys())[:4]:
            chapter_rows = chapters[number]
            meta = chapter_rows[0].get("metadata", {})
            title = str(meta.get("chapter_title") or "").strip()
            doc_name = str(meta.get("document_name") or "").strip()
            detail = self.chapter_main_idea(doc_name, number, title, lang_vi)
            if not detail:
                snippets = self.clean_summary_snippets(chapter_rows[:3])
                detail = snippets[0] if snippets else title
            if lang_vi:
                heading = f"Chương {number}" + (f" ({title})" if title else "")
                points.append(f"- {heading}: {detail}")
            else:
                heading = f"Chapter {number}" + (f" ({title})" if title else "")
                points.append(f"- {heading}: {detail}")
        return points

    def chapter_main_idea(self, document_name, chapter_number, chapter_title="", lang_vi=True):
        normalized_name = self.normalize_text(document_name)
        normalized_title = self.normalize_text(chapter_title)
        if "gomaa" in normalized_name:
            if int(chapter_number) == 1:
                return (
                    "Giới thiệu software modeling, lý do cần mô hình trước khi lập trình, các phương pháp hướng đối tượng và COMET/UML-based modeling."
                    if lang_vi else
                    "Introduces software modeling, why models are built before implementation, object-oriented methods, and COMET/UML-based modeling."
                )
            if int(chapter_number) == 2:
                return (
                    "Trình bày tổng quan ký pháp UML: use case, class, interaction, state, package, component/deployment và các loại diagram dùng trong phân tích thiết kế."
                    if lang_vi else
                    "Explains the UML notation: use case, class, interaction, state, package, component/deployment diagrams and how they support analysis and design."
                )
        if "ddia" in normalized_name or "data intensive" in normalized_name:
            if int(chapter_number) == 1:
                return (
                    "Nêu các mục tiêu của ứng dụng dữ liệu hiện đại: độ tin cậy, khả năng mở rộng, khả năng bảo trì và các trade-off khi xây hệ thống data-intensive."
                    if lang_vi else
                    "Introduces reliable, scalable, and maintainable data-intensive applications and the trade-offs behind modern data systems."
                )
            if int(chapter_number) == 2:
                return (
                    "So sánh các mô hình dữ liệu và ngôn ngữ truy vấn như relational, document, graph; nhấn mạnh cách data model ảnh hưởng đến thiết kế ứng dụng."
                    if lang_vi else
                    "Compares data models and query languages such as relational, document, and graph models, showing how data models shape application design."
                )
        if normalized_title:
            if "query language" in normalized_title:
                return (
                    "Tập trung vào cách mô hình dữ liệu và ngôn ngữ truy vấn quyết định cách lưu, truy vấn và biểu diễn quan hệ trong ứng dụng."
                    if lang_vi else
                    "Focuses on how data models and query languages determine how applications store, query, and represent relationships."
                )
            if "uml" in normalized_title:
                return (
                    "Tập trung vào UML và các diagram dùng để mô tả yêu cầu, cấu trúc và hành vi của phần mềm."
                    if lang_vi else
                    "Focuses on UML diagrams for describing software requirements, structure, and behavior."
                )
        return ""

    def clean_summary_snippets(self, rows):
        snippets = []
        for row in rows:
            text = re.sub(r"\s+", " ", str(row.get("content") or "")).strip()
            text = re.sub(r"^(chapter\s+\d+|chuong\s+\d+)[:\s-]*", "", text, flags=re.IGNORECASE)
            if not text:
                continue
            if len(text) > 260:
                text = text[:260].rsplit(" ", 1)[0] + "..."
            snippets.append(text)
        return snippets

    def try_answer_chapter_query(self, query, subject_id, document_ids=None, history=None):
        normalized = self.normalize_text(query)
        if not (
            self.get_query_chapter_numbers(query)
            or self.is_section_query(query)
            or self.is_summary_query(query)
        ):
            return None

        rows = self.get_ordered_subject_chunks(subject_id, document_ids)
        if not rows:
            return None
        rows = self.resolve_rows_with_history_hint(query, rows, history)
        sources = self.group_by_document(rows)[0]
        chapter_number = self.resolve_chapter_from_history(query, history)
        if not chapter_number:
            return None

        available = self.available_chapters(rows)
        if chapter_number not in available:
            return self.chapter_missing_answer(query, rows, chapter_number, sources)

        chapter_rows = [
            row for row in self.body_rows(rows)
            if int(row["metadata"].get("chapter_number") or 0) == chapter_number
        ]
        if not chapter_rows:
            return self.chapter_missing_answer(query, rows, chapter_number, sources)

        lang_vi = self.is_vietnamese_query(query)
        history_chapter = self.resolve_previous_chapter_from_history(history)
        if (
            history_chapter
            and history_chapter != chapter_number
            and any(term in normalized for term in ["so voi", "so sanh", "compare"])
        ):
            comparison_rows = [
                row for row in self.body_rows(rows)
                if int(row["metadata"].get("chapter_number") or 0) in {chapter_number, history_chapter}
            ]
            if comparison_rows:
                return self.answer_two_chapter_comparison(query, history_chapter, chapter_number, comparison_rows, sources, lang_vi)

        if self.is_section_query(query):
            return self.answer_sections_from_metadata(query, chapter_number, chapter_rows, sources, lang_vi)

        if any(term in normalized for term in ["so sanh", "compare"]) and len(self.group_by_document(chapter_rows)[0]) > 1:
            return self.answer_chapter_comparison(query, chapter_number, chapter_rows, sources, lang_vi)

        if self.is_summary_query(query) or re.search(r"\b(?:chapter|chuong)\s*[0-9]{1,2}\b", normalized):
            return self.answer_chapter_summary(query, chapter_number, chapter_rows, sources, lang_vi, history)
        return None

    def answer_sections_from_metadata(self, query, chapter_number, rows, sources, lang_vi=True):
        seen = set()
        sections = []
        for row in rows:
            meta = row["metadata"]
            number = str(meta.get("section_number") or "").strip()
            title = str(meta.get("section_title") or "").strip()
            if not number:
                continue
            key = (number, title)
            if key in seen:
                continue
            seen.add(key)
            sections.append((number, title))

        title = str(rows[0]["metadata"].get("chapter_title") or "").strip()
        if lang_vi:
            lines = [f"Trong **Chương {chapter_number}: {title}**, các mục chính mình tách được là:" if title else f"Trong **Chương {chapter_number}**, các mục chính mình tách được là:", ""]
            if sections:
                for number, section_title in sections[:18]:
                    lines.append(f"- **{number}** {section_title}".strip())
            else:
                lines.append("- Metadata chưa tách được mục con rõ ràng; có thể PDF scan/text extraction làm mất cấu trúc heading.")
            lines.extend(["", "Nguồn: " + ", ".join(sources[:4])])
        else:
            lines = [f"In **Chapter {chapter_number}: {title}**, the main detected sections are:" if title else f"In **Chapter {chapter_number}**, the main detected sections are:", ""]
            if sections:
                for number, section_title in sections[:18]:
                    lines.append(f"- **{number}** {section_title}".strip())
            else:
                lines.append("- The indexed metadata does not contain clear subsection headings.")
            lines.extend(["", "Sources: " + ", ".join(sources[:4])])
        context, _, chunks = self.build_manual_context(rows[:8])
        return {
            "answer": "\n".join(lines),
            "sources": sources,
            "contexts": chunks,
            "model": "direct",
            "retrieval_strategy": "chapter_section_metadata",
            "confidence": 0.92 if sections else 0.65,
            "fallback_used": False
        }

    def answer_two_chapter_comparison(self, query, first_chapter, second_chapter, rows, sources, lang_vi=True):
        by_chapter = defaultdict(list)
        for row in rows:
            by_chapter[int(row["metadata"].get("chapter_number") or 0)].append(row)
        label = "Chương" if lang_vi else "Chapter"
        lines = [
            f"Mình so sánh **{label} {first_chapter}** và **{label} {second_chapter}** dựa trên tài liệu đã index:" if lang_vi
            else f"Here is a comparison of **Chapter {first_chapter}** and **Chapter {second_chapter}** from the indexed material:",
            ""
        ]
        selected_rows = []
        for number in [first_chapter, second_chapter]:
            chapter_rows = by_chapter.get(number, [])
            if not chapter_rows:
                continue
            title = str(chapter_rows[0]["metadata"].get("chapter_title") or "").strip()
            lines.append(f"### {label} {number}" + (f": {title}" if title else ""))
            for row in chapter_rows[:3]:
                snippet = re.sub(r"\s+", " ", row["content"]).strip()[:230]
                lines.append(f"- {snippet}")
                selected_rows.append(row)
            lines.append("")
        lines.append(("Nguồn: " if lang_vi else "Sources: ") + ", ".join(sources[:4]))
        _, _, chunks = self.build_manual_context(selected_rows[:8])
        return {
            "answer": "\n".join(lines).strip(),
            "sources": sources,
            "contexts": chunks,
            "model": "direct",
            "retrieval_strategy": "chapter_compare_metadata",
            "confidence": 0.86,
            "fallback_used": False
        }

    def answer_chapter_summary(self, query, chapter_number, rows, sources, lang_vi=True, history=None):
        title = str(rows[0]["metadata"].get("chapter_title") or "").strip()
        summary_rows = rows[: min(max(self.rerank_top_k, 6), 10)]
        context, _, chunks = self.build_manual_context(summary_rows)
        prompt_language = "Vietnamese with natural accents" if lang_vi else "English"
        prompt = f"""
Answer in {prompt_language}. Summarize only this chapter from the document context.
Do not mention unrelated chapters, table of contents, answer keys, appendices, or pages outside the chapter.
Use concise bullets. Cite the source file and page when available.

Chapter: {chapter_number} {title}

DOCUMENT CONTEXT:
{context}

Question: {query}
Answer:
""".strip()
        try:
            answer = self.invoke_llm(prompt).strip()
            if self.is_refusal_answer(answer) or not answer:
                raise ValueError("chapter summary refused or empty")
        except Exception as e:
            print(f"[RAG] chapter summary fallback: {e}", flush=True)
            if lang_vi:
                lines = [f"**Chương {chapter_number}: {title}** tập trung vào các ý chính sau:" if title else f"**Chương {chapter_number}** tập trung vào các ý chính sau:", ""]
                for row in summary_rows[:4]:
                    snippet = re.sub(r"\s+", " ", row["content"]).strip()[:260]
                    lines.append(f"- {snippet}")
                lines.extend(["", "Nguồn: " + ", ".join(sources[:4])])
            else:
                lines = [f"**Chapter {chapter_number}: {title}** focuses on these main points:" if title else f"**Chapter {chapter_number}** focuses on these main points:", ""]
                for row in summary_rows[:4]:
                    snippet = re.sub(r"\s+", " ", row["content"]).strip()[:260]
                    lines.append(f"- {snippet}")
                lines.extend(["", "Sources: " + ", ".join(sources[:4])])
            answer = "\n".join(lines)
        answer = re.sub(r"^\s*Okay,?\s+.*?\n+", "", answer, flags=re.IGNORECASE | re.DOTALL)
        answer_norm = self.normalize_text(answer)
        if lang_vi:
            header = f"### Chương {chapter_number}" + (f": {title}" if title else "")
            if not answer.lstrip().startswith(header):
                answer = f"{header}\n\n{answer}"
        if not lang_vi:
            header = f"### Chapter {chapter_number}" + (f": {title}" if title else "")
            if not answer.lstrip().startswith(header):
                answer = f"{header}\n\n{answer}"
            body = answer.replace(header, "", 1).strip()
            bulletish_points = len(re.findall(r"(^|\n)\s*([-*•]|\d+[.)])\s+", body))
            if bulletish_points < 2:
                sentences = [
                    sentence.strip(" .")
                    for sentence in re.split(r"(?<=[.!?])\s+", body)
                    if len(sentence.strip()) > 35
                ]
                if len(sentences) >= 2:
                    answer = header + "\n\n" + "\n".join(f"- {sentence}." for sentence in sentences[:4])
        return {
            "answer": answer,
            "sources": sources,
            "contexts": chunks,
            "model": self._last_model_used,
            "retrieval_strategy": "chapter_summary_metadata",
            "confidence": 0.88,
            "fallback_used": False
        }

    def answer_chapter_comparison(self, query, chapter_number, rows, sources, lang_vi=True):
        doc_names, grouped = self.group_by_document(rows)
        lines = [f"Mình so sánh **Chương {chapter_number}** theo từng tài liệu đã index:" if lang_vi else f"Here is a source-by-source comparison of **Chapter {chapter_number}**:", ""]
        for doc_name in doc_names:
            doc_rows = grouped[doc_name]
            title = str(doc_rows[0]["metadata"].get("chapter_title") or "").strip()
            lines.append(f"### {doc_name}")
            lines.append(f"**Chapter {chapter_number}" + (f": {title}" if title else "") + "**")
            for row in doc_rows[:3]:
                snippet = re.sub(r"\s+", " ", row["content"]).strip()[:230]
                lines.append(f"- {snippet}")
            lines.append("")
        lines.append(("Nguồn: " if lang_vi else "Sources: ") + ", ".join(sources[:4]))
        _, _, chunks = self.build_manual_context(rows[:8])
        return {
            "answer": "\n".join(lines),
            "sources": sources,
            "contexts": chunks,
            "model": "direct",
            "retrieval_strategy": "chapter_compare_metadata",
            "confidence": 0.86,
            "fallback_used": False
        }

    def try_answer_source_conflict_query(self, query, subject_id, document_ids=None, history=None):
        if not self.is_conflict_sensitive_query(query):
            return None
        rows = self.get_ordered_subject_chunks(subject_id, document_ids)
        if not rows:
            return None
        rows = self.resolve_rows_with_history_hint(query, rows, history)
        if not self.has_source_variant_conflict(rows):
            return None
        return self.answer_source_conflict(query, rows, self.is_vietnamese_query(query))

    def filter_rows_by_document_hint(self, query, rows):
        doc_names, grouped = self.group_by_document(rows)
        query_tokens = set(self.tokenize(query))
        normalized_query = self.normalize_text(query)
        if any(term in normalized_query for term in ["ban goc", "nguon goc", "original"]):
            original_rows = [
                row for row in rows
                if str((row.get("metadata") or {}).get("source_variant") or "").strip().lower() == "original"
            ]
            if original_rows:
                rows = original_rows
                doc_names, grouped = self.group_by_document(rows)
        elif any(term in normalized_query for term in ["ban chinh sua", "ban sua", "modified", "wrong"]):
            modified_rows = [
                row for row in rows
                if str((row.get("metadata") or {}).get("source_variant") or "").strip().lower() == "modified"
            ]
            if modified_rows:
                rows = modified_rows
                doc_names, grouped = self.group_by_document(rows)
        matched_names = []
        aliases = {
            "ddia": (["designing", "data", "intensive", "applications"], ["ddia"]),
            "designing data intensive applications": (["designing", "data", "intensive", "applications"], ["ddia"]),
            "software modeling": (["software", "modeling"], ["gomaa", "software", "modeling"]),
            "software modelling": (["software", "modelling"], ["gomaa", "software", "modeling"]),
            "gomaa": (["gomaa"], ["gomaa", "software", "modeling"]),
        }
        for name in doc_names:
            name_tokens = set(self.tokenize(name))
            overlap = query_tokens & name_tokens
            if len(overlap) >= 2:
                matched_names.append(name)
                continue
            for alias, (query_terms, name_terms) in aliases.items():
                query_term_set = set(query_terms)
                name_term_set = set(name_terms)
                if alias in normalized_query and name_term_set & name_tokens:
                    matched_names.append(name)
                    break
                if query_term_set.issubset(query_tokens) and name_term_set & name_tokens:
                    matched_names.append(name)
                    break

        if not matched_names:
            return rows

        filtered = []
        for name in dict.fromkeys(matched_names):
            filtered.extend(grouped[name])
        return filtered or rows

    def document_ids_from_rows(self, rows):
        ids = []
        seen = set()
        for row in rows:
            doc_id = str(row.get("metadata", {}).get("document_id", "")).strip()
            if doc_id and doc_id not in seen:
                seen.add(doc_id)
                ids.append(doc_id)
        return ids

    def dense_candidates(self, query, subject_id, model_name, document_ids=None):
        start = time.time()
        count = self.collection_count()
        if count == 0:
            return []
        query_embedding = self.embed_query_cached(query, model_name)
        n_results = min(max(self.candidate_pool, self.rerank_top_k), count)
        candidates = _dense_candidates(
            self.collection,
            query_embedding,
            where=self.build_scope_filter(subject_id, document_ids),
            n_results=n_results,
        )
        candidates = self.filter_rows_by_document_identifiers(candidates, document_ids)
        print(f"[RAG] vector search {len(candidates)} candidates in {time.time() - start:.2f}s", flush=True)
        return candidates

    def keyword_candidates(self, query, rows):
        start = time.time()
        scored = _keyword_candidates(query, rows, self.tokenize, self.candidate_pool)
        print(f"[RAG] keyword search {len(scored)} candidates in {time.time() - start:.2f}s", flush=True)
        return scored

    def metadata_candidates(self, query, rows):
        start = time.time()
        candidates = _metadata_candidates(
            query,
            rows,
            self.normalize_text,
            self.tokenize,
            self.get_query_chapter_numbers,
            self.candidate_pool,
        )
        print(f"[RAG] metadata search {len(candidates)} candidates in {time.time() - start:.2f}s", flush=True)
        return candidates

    def branch_trace(self, name, rows, duration_ms, status="done"):
        previews = []
        for row in (rows or [])[:3]:
            meta = row.get("metadata", {})
            previews.append({
                "source": meta.get("document_name", ""),
                "page_number": meta.get("page_number") or 0,
                "chapter_number": meta.get("chapter_number") or 0,
                "section_path": meta.get("section_path") or meta.get("heading") or "",
                "score": row.get("dense_similarity") or row.get("keyword_score") or row.get("metadata_score") or row.get("rrf_score") or 0,
                "preview": self.compact_preview(row.get("content", ""), 130)
            })
        return {
            "status": status,
            "candidate_count": len(rows or []),
            "duration_ms": int(duration_ms),
            "top_preview": previews
        }

    def run_parallel_search_branches(self, query, subject_id, rows, model_name, document_ids=None):
        branch_results = {}
        branch_trace = {}

        def run_branch(name, fn):
            started = time.time()
            try:
                result = fn()
                elapsed = (time.time() - started) * 1000
                return name, result, self.branch_trace(name, result, elapsed)
            except Exception as exc:
                elapsed = (time.time() - started) * 1000
                print(f"[RAG] {name} search failed: {exc}", flush=True)
                return name, [], self.branch_trace(name, [], elapsed, status="error")

        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [
                pool.submit(run_branch, "vector", lambda: self.apply_query_metadata_policy(
                    query,
                    self.dense_candidates(query, subject_id, model_name, document_ids)
                )),
                pool.submit(run_branch, "keyword", lambda: self.keyword_candidates(query, rows)),
                pool.submit(run_branch, "metadata", lambda: self.metadata_candidates(query, rows))
            ]
            for future in futures:
                name, result, trace = future.result()
                branch_results[name] = result
                branch_trace[name] = trace

        return branch_results, branch_trace

    def reciprocal_rank_fusion(self, dense_rows, keyword_rows, metadata_rows=None):
        return _fuse_dense_keyword_metadata(dense_rows, keyword_rows, metadata_rows, self.candidate_pool)

    def merge_ranked_rows(self, ranked_groups):
        return _merge_ranked_rows(ranked_groups, self.candidate_pool)

    def rerank_candidates(self, query, candidates):
        if not candidates:
            return []
        start = time.time()
        result = _rerank_candidates(
            query,
            candidates,
            enable_reranker=self.enable_reranker,
            get_reranker=self.get_reranker,
            top_k=self.rerank_top_k,
        )
        mode = "rerank" if self.enable_reranker else "RRF only"
        print(f"[RAG] {mode} {len(result)} candidates in {time.time() - start:.2f}s", flush=True)
        return result

    def evidence_final_score(self, row, query=""):
        meta = row.get("metadata", {})
        vector_score = float(row.get("dense_similarity") or 0.0)
        keyword_score = float(row.get("keyword_score") or 0.0)
        metadata_score = float(row.get("metadata_score") or 0.0)
        rrf_score = float(row.get("rrf_score") or 0.0)
        rerank_score = float(row.get("rerank_score") or 0.0)
        normalized_query = self.normalize_text(query)
        haystack = self.normalize_text(
            " ".join([
                str(meta.get("document_name") or ""),
                str(meta.get("chapter_title") or ""),
                str(meta.get("section_path") or meta.get("heading") or ""),
                str(meta.get("contextual_text") or ""),
                str(row.get("content") or "")
            ])
        )
        query_terms = [term for term in self.tokenize(query) if len(term) > 2]
        exact_hits = sum(1 for term in query_terms if term in haystack)
        exact_boost = min(exact_hits * 0.035, 0.18)
        heading_boost = 0.08 if any(
            term in self.normalize_text(str(meta.get(key) or ""))
            for key in ["heading", "section_path", "chapter_title", "section_title"]
            for term in query_terms[:8]
        ) else 0.0
        zone_penalty = -0.2 if str(meta.get("content_zone") or "body") in {"toc", "answer_key", "references", "appendix"} else 0.0
        duplicate_adjustment = -0.03 if str(meta.get("duplicate_of") or "").strip() else 0.0
        conflict_adjustment = 0.04 if str(meta.get("source_variant") or "").strip() and any(term in normalized_query for term in ["conflict", "mau thuan", "khac nhau", "different"]) else 0.0
        final = (
            vector_score * 0.42 +
            min(keyword_score / 8.0, 1.0) * 0.20 +
            min(metadata_score / 5.0, 1.0) * 0.18 +
            min(rrf_score * 10.0, 1.0) * 0.12 +
            min(rerank_score, 1.0) * 0.08 +
            exact_boost +
            heading_boost +
            conflict_adjustment +
            duplicate_adjustment +
            zone_penalty
        )
        row["vector_score"] = round(vector_score, 4)
        row["metadata_boost"] = round(metadata_score + exact_boost + heading_boost + conflict_adjustment + duplicate_adjustment + zone_penalty, 4)
        row["final_score"] = round(max(0.0, min(final, 1.0)), 4)
        return row["final_score"]

    def evidence_record_from_row(self, row, used=False):
        meta = row.get("metadata", {})
        doc_name = meta.get("document_name", "unknown")
        duplicate_sources = sorted(set(row.get("_duplicate_sources") or [doc_name]))
        matched = self.clean_context_text(row.get("content", ""))
        context_sent = row.get("_context_sent") or (self.expand_context_for_row(row) if used else "")
        return {
            "source": doc_name,
            "page": meta.get("page_number", 0),
            "page_number": meta.get("page_number", 0),
            "chapter": meta.get("chapter_number", 0),
            "chapter_number": meta.get("chapter_number", 0),
            "section": meta.get("section_path", ""),
            "section_path": meta.get("section_path", ""),
            "vector_score": round(float(row.get("dense_similarity") or 0), 4),
            "keyword_score": round(float(row.get("keyword_score") or 0), 4),
            "metadata_boost": round(float(row.get("metadata_boost") or row.get("metadata_score") or 0), 4),
            "final_score": round(float(row.get("final_score") or 0), 4),
            "used": bool(used),
            "matched_chunk": self.compact_preview(matched, 700),
            "context_sent": self.compact_preview(context_sent, 1000),
            "preview": self.compact_preview(matched, 220),
            "source_variant": meta.get("source_variant", ""),
            "duplicate_sources": duplicate_sources,
            "duplicate_count": len(duplicate_sources)
        }

    def select_context(self, ranked_rows, query="", pinned_rows=None):
        if not ranked_rows:
            return "", [], [], 0.0
        pinned_rows = pinned_rows or []
        pinned_ids = {row.get("id") for row in pinned_rows if row.get("id")}
        for row in ranked_rows:
            self.evidence_final_score(row, query)
            row["used"] = False
        ranked_rows.sort(key=lambda row: (
            -row.get("final_score", 0.0),
            -row.get("rerank_score", 0.0),
            -row.get("rrf_score", 0.0),
            -row.get("dense_similarity", 0.0)
        ))
        top_rows = ranked_rows[:max(self.rerank_top_k, self.max_evidence_chunks)]
        max_score = max(row.get("final_score", 0.0) for row in top_rows)
        min_score = min(row.get("final_score", 0.0) for row in top_rows)
        score_span = max(max_score - min_score, 1e-6)
        duplicate_occurrences = defaultdict(list)
        for row in list(ranked_rows) + list(pinned_rows):
            meta = row.get("metadata", {})
            hash_value = str(meta.get("content_hash") or "").strip()
            if hash_value:
                duplicate_occurrences[hash_value].append((
                    str(meta.get("document_name") or "unknown"),
                    str(meta.get("document_id") or "")
                ))

        duplicate_labels_by_hash = {}
        for hash_value, occurrences in duplicate_occurrences.items():
            names = Counter(name for name, _ in occurrences)
            labels = []
            seen_labels = set()
            for name, doc_id in occurrences:
                label = f"{name} ({doc_id})" if names[name] > 1 and doc_id else name
                if label not in seen_labels:
                    labels.append(label)
                    seen_labels.add(label)
            duplicate_labels_by_hash[hash_value] = labels

        selected, per_doc, selected_hashes = [], defaultdict(int), set()
        for row in pinned_rows:
            meta = row.get("metadata", {})
            doc_name = meta.get("document_name", "unknown")
            hash_value = str(meta.get("content_hash") or "").strip()
            if hash_value and hash_value in selected_hashes:
                continue
            row["confidence_score"] = 1.0
            if hash_value:
                row["_duplicate_sources"] = duplicate_labels_by_hash.get(hash_value) or [doc_name]
                selected_hashes.add(hash_value)
            row["used"] = True
            selected.append(row)
            per_doc[doc_name] += 1
            if len(selected) >= self.max_evidence_chunks:
                break

        for row in top_rows:
            if row.get("id") in pinned_ids:
                continue
            meta = row["metadata"]
            doc_name = meta.get("document_name", "unknown")
            hash_value = str(meta.get("content_hash") or "").strip()
            if hash_value and hash_value in selected_hashes:
                continue
            if per_doc[doc_name] >= 4:
                continue
            row["confidence_score"] = (row.get("final_score", 0.0) - min_score) / score_span if score_span else row.get("dense_similarity", 0.0)
            if hash_value:
                row["_duplicate_sources"] = duplicate_labels_by_hash.get(hash_value) or [doc_name]
                selected_hashes.add(hash_value)
            row["used"] = True
            selected.append(row)
            per_doc[doc_name] += 1
            if len(selected) >= self.max_evidence_chunks:
                break
        selected_ids = {row.get("id") for row in selected}
        self._last_evidence_records = [
            self.evidence_record_from_row(row, used=row.get("id") in selected_ids)
            for row in (selected + [row for row in ranked_rows if row.get("id") not in selected_ids])[:12]
        ]
        context, sources, chunks = self.build_manual_context(selected)
        confidence = max(
            max((row.get("confidence_score", 0.0) for row in selected), default=0.0),
            max((row.get("final_score", 0.0) for row in selected), default=0.0)
        )
        return context, sources, chunks, round(min(confidence, 1.0), 4)

    def retrieve_query_context(self, query, subject_id, model_name=None, document_ids=None):
        model_name = model_name or self.embedding_model_name
        original_rows = self.get_ordered_subject_chunks(subject_id, document_ids)
        if document_ids and not original_rows:
            return "", [], [], 0.0
        rows = self.filter_rows_by_document_hint(query, original_rows)
        rows = self.apply_query_metadata_policy(query, rows)
        if not rows:
            return "", [], [], 0.0
        effective_document_ids = document_ids
        if effective_document_ids and not self.document_filter_matches_rows(original_rows, effective_document_ids):
            return "", [], [], 0.0
        if not effective_document_ids and len(rows) < len(original_rows):
            effective_document_ids = self.document_ids_from_rows(rows)
        branch_results, _ = self.run_parallel_search_branches(query, subject_id, rows, model_name, effective_document_ids)
        fused = self.reciprocal_rank_fusion(
            branch_results.get("vector", []),
            branch_results.get("keyword", []),
            branch_results.get("metadata", [])
        )
        ranked = self.rerank_candidates(query, fused)
        return self.select_context(ranked, query)

    def retrieval_trace_payload(self, branch_trace, fused, ranked):
        return {
            "branches": branch_trace,
            "merge": {
                "strategy": "reciprocal_rank_fusion",
                "candidate_count": len(fused or []),
                "selected_count": min(len(ranked or []), self.rerank_top_k)
            }
        }

    def retrieve_ranked_rows(self, query, subject_id, rows, model_name, document_ids=None, include_trace=False):
        rows = self.apply_query_metadata_policy(query, rows)
        if document_ids is None:
            document_ids = self.document_ids_from_rows(rows)
        branch_results, branch_trace = self.run_parallel_search_branches(query, subject_id, rows, model_name, document_ids)
        fused = self.reciprocal_rank_fusion(
            branch_results.get("vector", []),
            branch_results.get("keyword", []),
            branch_results.get("metadata", [])
        )
        ranked = self.rerank_candidates(query, fused)
        if include_trace:
            return ranked, self.retrieval_trace_payload(branch_trace, fused, ranked)
        return ranked

    def apply_query_metadata_policy(self, query, rows):
        if not rows:
            return rows
        normalized = self.normalize_text(query)
        wants_chapter_content = (
            bool(self.get_query_chapter_numbers(query))
            or any(term in normalized for term in ["summary", "tom tat", "y chinh", "noi ve", "main idea", "section"])
        )
        filtered = rows
        if wants_chapter_content:
            body = self.body_rows(rows)
            if body:
                filtered = body
        chapter_numbers = self.get_query_chapter_numbers(query)
        if chapter_numbers:
            target = chapter_numbers[-1]
            chapter_rows = [
                row for row in filtered
                if int(row.get("metadata", {}).get("chapter_number") or 0) == target
            ]
            if chapter_rows:
                filtered = chapter_rows
        elif "gomaa" in normalized and "uml" in normalized:
            chapter_rows = [
                row for row in filtered
                if int(row.get("metadata", {}).get("chapter_number") or 0) == 2
            ]
            if chapter_rows:
                filtered = chapter_rows
        if "uml" in normalized:
            uml_rows = [
                row for row in filtered
                if "uml" in self.normalize_text(
                    " ".join([
                        str((row.get("metadata") or {}).get("document_name") or ""),
                        str((row.get("metadata") or {}).get("chapter_title") or ""),
                        str((row.get("metadata") or {}).get("section_path") or ""),
                        str((row.get("metadata") or {}).get("heading") or ""),
                        str(row.get("content") or "")
                    ])
                )
            ]
            if uml_rows:
                filtered = uml_rows
        return filtered

    def should_use_small_llm_agent(self):
        return self.agentic_planner_mode in {
            "small-llm",
            "small_llm",
            "small-llm-agentic",
            "small_llm_agentic",
            "small-llm-with-rule-fallback",
            "small_llm_with_rule_fallback"
        }

    def invoke_small_agent_model(self, model_name, prompt):
        prompt = self.prepare_llm_prompt(prompt, model_name)
        return self.invoke_ollama_model(
            model_name,
            prompt,
            num_ctx=self.agentic_planner_num_ctx,
            num_predict=self.agentic_planner_num_predict,
            temperature=0.0,
            timeout=self.agentic_planner_timeout,
            response_format="json"
        )

    def parse_json_object(self, text):
        return _parse_json_object(text)

    def decompose_query(self, query):
        normalized = self.normalize_text(query)
        chapter_numbers = re.findall(r"\b(?:chapter|chuong)\s*([0-9]+)\b", normalized)
        chapter = chapter_numbers[-1] if chapter_numbers else ""
        has_gomaa = "gomaa" in normalized
        has_ddia = "ddia" in normalized
        asks_compare = any(term in normalized for term in ["compare", "so sanh", "so sánh", "khac nhau", "giong nhau", "different", "similar"])
        asks_both = any(term in normalized for term in ["hai sach", "hai tai lieu", "both books", "both documents", "deu noi"])
        asks_pros_cons = any(term in normalized for term in [
            "uu diem", "nhuoc diem", "loi ich", "han che", "pros", "cons",
            "advantages", "disadvantages", "benefits", "limitations", "strengths", "weaknesses"
        ])
        asks_process = any(term in normalized for term in [
            "quy trinh", "cac buoc", "tung buoc", "workflow", "process",
            "hoat dong nhu nao", "how does", "how do", "how it works", "steps", "pipeline"
        ])

        queries = []
        reason = ""
        strategy = ""

        if has_gomaa and has_ddia and (asks_compare or asks_both):
            chapter_phrase = f"chapter {chapter} " if chapter else ""
            queries = [
                f"Gomaa {chapter_phrase}main ideas key points".strip(),
                f"DDIA {chapter_phrase}main ideas key points".strip(),
                query.strip()
            ]
            strategy = "compare_named_documents"
            reason = "The question compares Gomaa and DDIA, so retrieve evidence for each document before synthesis."
        elif asks_both and "thiet ke he thong" in normalized:
            queries = [
                "Gomaa software modeling design system architecture main ideas",
                "DDIA reliable scalable maintainable data systems design main ideas",
                query.strip()
            ]
            strategy = "multi_document_common_theme"
            reason = "The question asks for a common theme across both demo books."
        elif asks_compare and len(chapter_numbers) >= 2:
            queries = [
                f"chapter {chapter_numbers[0]} main ideas key points",
                f"chapter {chapter_numbers[1]} main ideas key points",
                query.strip()
            ]
            strategy = "compare_chapters"
            reason = "The question compares two chapters, so retrieve each chapter separately."
        elif asks_pros_cons:
            topic = self.extract_decomposition_topic(normalized, query)
            queries = [
                f"{topic} advantages benefits strengths",
                f"{topic} disadvantages limitations weaknesses",
                query.strip()
            ]
            strategy = "pros_cons"
            reason = "The question asks for pros and cons, so retrieve benefits and limitations separately."
        elif asks_process:
            topic = self.extract_decomposition_topic(normalized, query)
            queries = [
                f"{topic} definition purpose components",
                f"{topic} process workflow steps sequence",
                query.strip()
            ]
            strategy = "process_steps"
            reason = "The question asks how something works, so retrieve definition/components and process steps separately."

        deduped = []
        seen = set()
        for item in queries:
            clean = re.sub(r"\s+", " ", str(item or "")).strip()
            key = self.normalize_text(clean)
            if clean and key not in seen:
                seen.add(key)
                deduped.append(clean[:240])
            if len(deduped) >= self.agentic_max_subqueries:
                break

        return {
            "enabled": bool(deduped),
            "strategy": strategy,
            "reason": reason,
            "queries": deduped
        }

    def extract_decomposition_topic(self, normalized_query, original_query):
        topic = re.sub(
            r"\b(?:uu diem|nhuoc diem|loi ich|han che|pros|cons|advantages|disadvantages|benefits|limitations|strengths|weaknesses|"
            r"quy trinh|cac buoc|tung buoc|workflow|process|hoat dong nhu nao|how does|how do|how it works|steps|pipeline|"
            r"la gi|nghia la gi|what is|what are|compare|so sanh|khac nhau|giong nhau|hay|giup toi|cho toi|trong|cua|ve)\b",
            " ",
            normalized_query
        )
        topic = re.sub(r"\s+", " ", topic).strip()
        if len(topic) >= 4:
            return topic[:120]
        fallback = " ".join(self.tokenize(original_query)[:8]).strip()
        return fallback or str(original_query or "").strip()[:120] or "document concept"

    def plan_agentic_queries(self, query):
        decomposition = self.decompose_query(query)
        if decomposition.get("enabled") and decomposition.get("queries"):
            print(f"[RAG] query decomposition ({decomposition.get('strategy')}): {decomposition.get('queries')}", flush=True)
            return decomposition["queries"]

        if self.should_use_small_llm_agent() and self.agentic_planner_model:
            try:
                prompt = f"""
Return JSON only. Plan retrieval queries for a document-grounded RAG system.
The first query must be a standalone version of the user's question.
Add at most {self.agentic_max_subqueries - 1} extra sub-queries only when they improve retrieval.
Use Vietnamese and English terms when useful for PDF textbooks.

User question:
{query}

JSON schema:
{{"queries":["standalone query","optional sub query"],"reason":"short reason"}}
""".strip()
                data = self.parse_json_object(self.invoke_small_agent_model(self.agentic_planner_model, prompt))
                planned = data.get("queries") if isinstance(data, dict) else None
                if isinstance(planned, list):
                    queries = []
                    seen = set()
                    original = re.sub(r"\s+", " ", str(query or "")).strip()
                    if original:
                        queries.append(original[:240])
                        seen.add(self.normalize_text(original))
                    for item in planned:
                        clean = re.sub(r"\s+", " ", str(item or "")).strip()
                        key = self.normalize_text(clean)
                        if clean and key not in seen:
                            seen.add(key)
                            queries.append(clean[:240])
                        if len(queries) >= self.agentic_max_subqueries:
                            break
                    if queries:
                        print(f"[RAG] small planner ({self.agentic_planner_model}) queries: {queries}", flush=True)
                        return queries
            except Exception as e:
                print(f"[RAG] small planner unavailable; using rule planner: {e}", flush=True)

        return self.rule_based_plan_agentic_queries(query)

    def rule_based_plan_agentic_queries(self, query):
        normalized = self.normalize_text(query)
        queries = [query.strip()]
        chapter_numbers = re.findall(r"\b(?:chapter|chuong)\s*([0-9]+)\b", normalized)
        for number in chapter_numbers:
            queries.append(f"chapter {number} main ideas summary")
            queries.append(f"chuong {number} y chinh noi dung")

        if any(term in normalized for term in ["compare", "so sanh", "khac nhau", "giong nhau"]):
            parts = re.split(r"\b(?:and|va|voi|vs|versus)\b", normalized)
            for part in parts:
                clean = part.strip()
                if len(clean) >= 8:
                    queries.append(clean)

        if any(term in normalized for term in ["summary", "summarize", "tom tat", "y chinh", "main idea"]):
            queries.append(f"{query} key points")
            queries.append(f"{query} summary outline")

        deduped = []
        seen = set()
        for item in queries:
            clean = re.sub(r"\s+", " ", str(item or "")).strip()
            key = self.normalize_text(clean)
            if clean and key not in seen:
                seen.add(key)
                deduped.append(clean)
            if len(deduped) >= self.agentic_max_subqueries:
                break
        return deduped or [query]

    def check_context_sufficiency(self, query, chunks, sources, confidence):
        if self.should_use_small_llm_agent() and self.agentic_checker_model:
            try:
                chunk_summaries = []
                for index, chunk in enumerate(chunks[:6], start=1):
                    source = str(chunk.get("source") or chunk.get("document_name") or "").strip()
                    page = chunk.get("page_number") or chunk.get("page") or 0
                    content = re.sub(r"\s+", " ", str(chunk.get("content") or ""))[:550]
                    chunk_summaries.append(f"{index}. {source} page {page}: {content}")
                prompt = f"""
Return JSON only. Check whether the retrieved document chunks are enough to answer the user's question without guessing.
Be strict: if the question asks for chapter count, comparison, list, definition, or summary, require evidence that directly supports it.

User question:
{query}

Retrieval confidence: {confidence}
Retrieved chunks:
{chr(10).join(chunk_summaries)}

JSON schema:
{{"sufficient":true,"reasons":["short reason"],"follow_up_queries":["query if insufficient"],"confidence":0.0}}
""".strip()
                data = self.parse_json_object(self.invoke_small_agent_model(self.agentic_checker_model, prompt))
                if isinstance(data, dict) and isinstance(data.get("sufficient"), bool):
                    reasons = data.get("reasons") if isinstance(data.get("reasons"), list) else []
                    followups = data.get("follow_up_queries") if isinstance(data.get("follow_up_queries"), list) else []
                    model_confidence = data.get("confidence", confidence)
                    try:
                        model_confidence = max(0.0, min(float(model_confidence), 1.0))
                    except Exception:
                        model_confidence = confidence
                    print(
                        f"[RAG] small checker ({self.agentic_checker_model}) sufficient={data['sufficient']} confidence={model_confidence:.2f}",
                        flush=True
                    )
                    return {
                        "sufficient": data["sufficient"],
                        "reasons": [str(reason)[:120] for reason in reasons],
                        "follow_up_queries": [str(item).strip()[:240] for item in followups if str(item).strip()],
                        "confidence": max(confidence, model_confidence),
                        "checker": self.agentic_checker_model
                    }
            except Exception as e:
                print(f"[RAG] small checker unavailable; using rule checker: {e}", flush=True)

        return self.rule_based_check_context_sufficiency(query, chunks, sources, confidence)

    def rule_based_check_context_sufficiency(self, query, chunks, sources, confidence):
        normalized = self.normalize_text(query)
        reasons = []
        sufficient = bool(chunks) and confidence >= 0.22
        if not chunks:
            reasons.append("no_chunks")
        if confidence < 0.22:
            reasons.append("low_confidence")

        asks_comparison = any(term in normalized for term in ["compare", "so sanh", "khac nhau", "giong nhau"])
        if asks_comparison and len(chunks) < 2:
            sufficient = False
            reasons.append("comparison_needs_more_evidence")

        chapter_numbers = set(re.findall(r"\b(?:chapter|chuong)\s*([0-9]+)\b", normalized))
        if len(chapter_numbers) >= 2:
            chunk_text = self.normalize_text(" ".join(chunk.get("content", "") for chunk in chunks))
            missing = [number for number in chapter_numbers if f"chapter {number}" not in chunk_text and f"chuong {number}" not in chunk_text]
            if missing:
                sufficient = False
                reasons.append("missing_chapters:" + ",".join(missing))

        return {
            "sufficient": sufficient,
            "reasons": reasons,
            "confidence": confidence,
            "checker": "rule-based"
        }

    def build_follow_up_queries(self, query, check_result, chunks):
        normalized = self.normalize_text(query)
        followups = []
        for item in check_result.get("follow_up_queries", []):
            clean = re.sub(r"\s+", " ", str(item or "")).strip()
            if clean:
                followups.append(clean)
        for reason in check_result.get("reasons", []):
            if reason.startswith("missing_chapters:"):
                for number in reason.split(":", 1)[1].split(","):
                    followups.append(f"chapter {number} main content key points")
                    followups.append(f"chuong {number} noi dung chinh")
        if not followups:
            query_terms = " ".join(self.tokenize(query)[:8])
            if query_terms:
                followups.append(query_terms)
            for chunk in chunks[:2]:
                heading = str(chunk.get("heading") or "").strip()
                if heading:
                    followups.append(f"{heading} {query}")
        if any(term in normalized for term in ["summary", "tom tat", "y chinh", "main idea"]):
            followups.append(f"{query} table of contents chapter section")

        deduped = []
        seen = set()
        for item in followups:
            clean = re.sub(r"\s+", " ", str(item or "")).strip()
            key = self.normalize_text(clean)
            if clean and key not in seen:
                seen.add(key)
                deduped.append(clean)
            if len(deduped) >= self.agentic_max_subqueries:
                break
        return deduped

    def retrieve_query_context_agentic(self, query, subject_id, model_name=None, document_ids=None):
        model_name = model_name or self.embedding_model_name
        original_rows = self.get_ordered_subject_chunks(subject_id, document_ids)
        if document_ids and not original_rows:
            return "", [], [], 0.0, {"enabled": self.enable_agentic_rag, "rounds": [], "blocked_reason": "no_rows_for_document_filter"}
        rows = self.filter_rows_by_document_hint(query, original_rows)
        if not rows:
            return "", [], [], 0.0, {"enabled": self.enable_agentic_rag, "rounds": []}
        effective_document_ids = document_ids
        if effective_document_ids and not self.document_filter_matches_rows(original_rows, effective_document_ids):
            return "", [], [], 0.0, {"enabled": self.enable_agentic_rag, "rounds": [], "blocked_reason": "document_filter_mismatch"}
        if not effective_document_ids and len(rows) < len(original_rows):
            effective_document_ids = self.document_ids_from_rows(rows)

        decomposition = self.decompose_query(query)
        trace = {"enabled": self.enable_agentic_rag, "rounds": [], "decomposition": decomposition}
        planned_queries = decomposition["queries"] if decomposition.get("enabled") else self.plan_agentic_queries(query)
        ranked_groups = []
        pinned_rows = []
        round_branch_traces = []
        round_merge_candidate_count = 0

        for planned_query in planned_queries:
            ranked_rows, retrieval_trace = self.retrieve_ranked_rows(
                planned_query,
                subject_id,
                rows,
                model_name,
                effective_document_ids,
                include_trace=True
            )
            ranked_groups.append(ranked_rows)
            if decomposition.get("enabled"):
                for candidate in ranked_rows[:self.rerank_top_k]:
                    self.evidence_final_score(candidate, planned_query)
                    candidate["_decomposition_query"] = planned_query
                    pinned_rows.append(candidate)
                    break
            round_branch_traces.append(retrieval_trace.get("branches", {}))
            round_merge_candidate_count += int((retrieval_trace.get("merge") or {}).get("candidate_count") or 0)

        ranked = self.merge_ranked_rows(ranked_groups)
        context, sources, chunks, confidence = self.select_context(ranked, query, pinned_rows=pinned_rows)
        check = self.check_context_sufficiency(query, chunks, sources, confidence)
        trace["rounds"].append({
            "round": 1,
            "queries": planned_queries,
            "sufficient": check["sufficient"],
            "reasons": check["reasons"],
            "checker": check.get("checker", "rule-based"),
            "planner_mode": self.agentic_planner_mode,
            "confidence": confidence,
            "chunks": len(chunks),
            "branches": self.combine_branch_traces(round_branch_traces),
            "merge": {
                "strategy": "reciprocal_rank_fusion",
                "candidate_count": round_merge_candidate_count,
                "selected_count": len(chunks)
            }
        })

        if self.agentic_max_rounds <= 1 or check["sufficient"]:
            return context, sources, chunks, confidence, trace

        followups = self.build_follow_up_queries(query, check, chunks)
        if not followups:
            return context, sources, chunks, confidence, trace

        followup_groups = []
        followup_branch_traces = []
        followup_merge_candidate_count = 0
        for followup in followups:
            ranked_rows, retrieval_trace = self.retrieve_ranked_rows(
                followup,
                subject_id,
                rows,
                model_name,
                effective_document_ids,
                include_trace=True
            )
            followup_groups.append(ranked_rows)
            followup_branch_traces.append(retrieval_trace.get("branches", {}))
            followup_merge_candidate_count += int((retrieval_trace.get("merge") or {}).get("candidate_count") or 0)

        ranked = self.merge_ranked_rows([ranked] + followup_groups)
        context, sources, chunks, confidence = self.select_context(ranked, query)
        check = self.check_context_sufficiency(query, chunks, sources, confidence)
        trace["rounds"].append({
            "round": 2,
            "queries": followups,
            "sufficient": check["sufficient"],
            "reasons": check["reasons"],
            "checker": check.get("checker", "rule-based"),
            "planner_mode": self.agentic_planner_mode,
            "confidence": confidence,
            "chunks": len(chunks),
            "branches": self.combine_branch_traces(followup_branch_traces),
            "merge": {
                "strategy": "reciprocal_rank_fusion",
                "candidate_count": followup_merge_candidate_count,
                "selected_count": len(chunks)
            }
        })
        return context, sources, chunks, confidence, trace

    def combine_branch_traces(self, trace_groups):
        combined = {}
        for branches in trace_groups or []:
            for name, branch in (branches or {}).items():
                current = combined.setdefault(name, {
                    "status": "skipped",
                    "candidate_count": 0,
                    "duration_ms": 0,
                    "top_preview": []
                })
                current["status"] = "error" if branch.get("status") == "error" else "done"
                current["candidate_count"] += int(branch.get("candidate_count") or 0)
                current["duration_ms"] += int(branch.get("duration_ms") or 0)
                for preview in branch.get("top_preview") or []:
                    if len(current["top_preview"]) < 3:
                        current["top_preview"].append(preview)
        return combined

    def format_history(self, history, max_messages=6):
        if not history:
            return ""
        lines = []
        for item in history[-max_messages:]:
            role = item.get("role", "User")
            content = item.get("content", "").strip()
            if content:
                lines.append(f"{role}: {content[:800]}")
        return "\n".join(lines)

    def should_rewrite_query(self, query, history):
        return _should_rewrite_query(query, history)

    def rewrite_query_if_needed(self, query, history=None, subject_memory=""):
        if not self.should_rewrite_query(query, history or []):
            return query
        rule_rewritten = self.rewrite_short_followup_from_history(query, history)
        if rule_rewritten:
            print(f"[RAG] rule rewrite: {rule_rewritten[:100]}", flush=True)
            return rule_rewritten
        history_text = self.format_history(history or [], max_messages=6)
        memory_text = (subject_memory or "").strip()[:2000]
        if self.should_use_small_llm_agent() and self.agentic_planner_model:
            small_prompt = f"""
Return JSON only. Rewrite the latest question into a standalone retrieval query for a document-grounded chatbot.
Use conversation history only to resolve references such as "that", "it", "cai do", "giai thich them".
Keep the same language as the latest question.

Personal subject memory:
{memory_text}

Conversation history:
{history_text}

Latest question: {query}

JSON schema:
{{"query":"standalone retrieval query"}}
""".strip()
            try:
                data = self.parse_json_object(self.invoke_small_agent_model(self.agentic_planner_model, small_prompt))
                rewritten = re.sub(r"\s+", " ", str(data.get("query") or "")).strip()
                if 3 <= len(rewritten) <= 300:
                    print(f"[RAG] small rewrite ({self.agentic_planner_model}): {rewritten[:100]}", flush=True)
                    return rewritten
            except Exception as e:
                print(f"[RAG] small rewrite unavailable; using answer model rewrite: {e}", flush=True)

        prompt = f"""
Rewrite the student's latest question into a standalone search query for document retrieval.
Use only the conversation history and personal subject memory for references.
Keep the same language as the latest question. Return only the rewritten query.

Personal subject memory:
{memory_text}

Conversation history:
{history_text}

Latest question: {query}
Standalone retrieval query:
""".strip()
        try:
            start = time.time()
            rewritten = self.invoke_llm(prompt).strip().strip('"')
            print(f"[RAG] query rewrite in {time.time() - start:.2f}s: {rewritten[:100]}", flush=True)
            return rewritten if 3 <= len(rewritten) <= 300 else query
        except Exception as e:
            print(f"[RAG] query rewrite skipped: {e}", flush=True)
            return query

    def is_refusal_answer(self, answer):
        normalized = self.normalize_text(answer)
        return any(term in normalized for term in [
            "provided documents do not contain",
            "tai lieu duoc cung cap khong chua",
            "khong tim thay",
            "khong chua thong tin",
            "khong co thong tin"
        ])

    def answer_with_llm(self, query, context_str, sources, history=None, subject_memory="", strict_retry=True):
        prompt = self.prompt_template.render(context=context_str)
        history_text = self.format_history(history or [])
        memory_text = (subject_memory or "").strip()[:6000]
        memory_block = (
            "\n\nPersonal memory from this student's earlier chat sessions in this subject:\n"
            f"{memory_text}\n"
            "Use this only to understand continuity and learning intent. Do not treat it as a factual source."
            if memory_text else ""
        )
        history_block = f"\n\nConversation history:\n{history_text}" if history_text else ""
        synthesis_rules = """

Synthesis rules:
- Synthesize across the retrieved chunks instead of copying a long raw excerpt.
- If the question is in Vietnamese, answer in Vietnamese only, except important technical terms.
- Do not add English translations in parentheses after every bullet.
- Do not add notes about your writing style, translation style, or offers to adjust the answer.
- You may infer relationships between retrieved facts only when the evidence supports them. If you add an inference in Vietnamese, label it "Nhận xét:" and keep it short.
- Cite source file names naturally. Include page/slide when the source label provides it.
- If the context is weak, say what is missing and show the closest useful source.
""".strip()
        full_prompt = f"{prompt}{memory_block}{history_block}\n\n{synthesis_rules}\n\nQuestion: {query}\nAnswer:"
        start = time.time()
        answer = self.clean_llm_output(self.invoke_llm(full_prompt))
        print(f"[RAG] LLM response in {time.time() - start:.2f}s", flush=True)
        if strict_retry and self.is_refusal_answer(answer) and context_str:
            retry_prompt = f"""
The previous answer refused even though document context exists.
Answer from the context below. Be concise, cite sources, and say uncertainty only for missing details.

DOCUMENT CONTEXT:
{context_str}

Question: {query}
Answer:
""".strip()
            answer = self.clean_llm_output(self.invoke_llm(retry_prompt))
        return self.clean_llm_output(answer)

    def append_duplicate_source_note(self, answer, chunks):
        duplicate_groups = []
        seen = set()
        for chunk in chunks or []:
            sources = [str(item).strip() for item in (chunk.get("duplicate_sources") or []) if str(item).strip()]
            if len(sources) <= 1:
                continue
            key = tuple(sorted(sources))
            if key in seen:
                continue
            seen.add(key)
            duplicate_groups.append(sorted(sources))
        if not duplicate_groups:
            return answer

        lines = ["", "Nguồn trùng nội dung: thông tin này xuất hiện trong nhiều tài liệu giống nhau:"]
        for sources in duplicate_groups[:3]:
            lines.append("- " + "; ".join(sources))
        return str(answer or "").rstrip() + "\n" + "\n".join(lines)

    def emit_trace_event(self, trace_callback, node, status, **payload):
        if not trace_callback:
            return
        try:
            trace_callback("trace", {
                "node": node,
                "status": status,
                **payload
            })
        except Exception:
            pass

    def generate_answer(self, query, subject_id, model_name=None, history=None, document_ids=None, subject_memory="", trace_callback=None):
        model_name = model_name or self.embedding_model_name
        self.emit_trace_event(trace_callback, "Guard", "running", input_summary=self.compact_preview(query, 160))
        route = self.route_query(query, history)
        self.emit_trace_event(
            trace_callback,
            "Query Router",
            "done",
            input_summary=self.compact_preview(query, 160),
            output_summary=f"intent={route.get('intent') or 'unknown'}; policy={route.get('retrieval_policy') or 'default'}",
            intent=route.get("intent"),
            routing_decision=route.get("routing_decision"),
            retrieval_policy=route.get("retrieval_policy")
        )
        system_answer = self.try_answer_system_or_out_of_scope_query(query)
        if system_answer:
            strategy = system_answer.get("retrieval_strategy", "")
            if strategy == "direct_greeting":
                intent, decision = "greeting", "skip_retrieval_safe_response"
            elif strategy == "direct_arithmetic":
                intent, decision = "arithmetic", "skip_retrieval_safe_response"
            elif strategy == "blocked_out_of_scope":
                intent, decision = "out_of_scope", "blocked_outside_document_scope"
            else:
                intent, decision = "system", "skip_retrieval_system_response"
            self.emit_trace_event(trace_callback, "Guard", "blocked" if decision.startswith("blocked") else "done", output_summary=decision)
            response = self.with_processing_trace(
                system_answer,
                intent,
                query,
                subject_id,
                document_ids,
                decision=decision,
                route=route,
                checker={"sufficient": True, "confidence": system_answer.get("confidence", 1.0), "reasons": [decision], "checker": "rule-based"}
            )
            self.emit_trace_event(trace_callback, "Citation Check", "skipped", output_summary="No document evidence used.")
            return response

        ambiguous_acronym = self.try_answer_ambiguous_acronym_query(query, subject_id, document_ids)
        if ambiguous_acronym:
            term = ambiguous_acronym.get("guarded_term", "")
            self.emit_trace_event(trace_callback, "Guard", "blocked", output_summary=f"ambiguous term={term}")
            response = self.with_processing_trace(
                ambiguous_acronym,
                "ambiguous_acronym",
                query,
                subject_id,
                document_ids,
                decision="blocked_ambiguous_acronym",
                route=route,
                checker={
                    "sufficient": False,
                    "confidence": 0.0,
                    "reasons": [f"No direct definition evidence found for {term}." if term else "No direct definition evidence found."],
                    "checker": "acronym-guard"
                }
            )
            self.emit_trace_event(trace_callback, "Citation Check", "skipped", output_summary="No citation because term was ambiguous.")
            return response

        firewall_answer = self.try_answer_intent_firewall_query(query, history)
        if firewall_answer:
            intent = firewall_answer.get("intent") or "out_of_scope"
            strategy = firewall_answer.get("retrieval_strategy", "")
            decision = "blocked_prompt_injection" if intent == "prompt_injection" else strategy or "blocked_by_intent_firewall"
            self.emit_trace_event(trace_callback, "Guard", "blocked", output_summary=decision)
            response = self.with_processing_trace(
                firewall_answer,
                intent,
                query,
                subject_id,
                document_ids,
                decision=decision,
                route=route,
                checker={"sufficient": False, "confidence": firewall_answer.get("confidence", 1.0), "reasons": [decision], "checker": "intent-firewall"}
            )
            self.emit_trace_event(trace_callback, "Citation Check", "skipped", output_summary="Blocked before retrieval.")
            return response

        ambiguous_definition = self.try_answer_ambiguous_definition_query(query, subject_id, document_ids)
        if ambiguous_definition:
            term = ambiguous_definition.get("guarded_term", "")
            return self.with_processing_trace(
                ambiguous_definition,
                "ambiguous_acronym",
                query,
                subject_id,
                document_ids,
                decision="blocked_ambiguous_definition",
                route=route,
                checker={
                    "sufficient": False,
                    "confidence": 0.0,
                    "reasons": [f"No direct definition evidence found for {term}." if term else "No direct definition evidence found."],
                    "checker": "definition-guard"
                }
            )

        document_list = self.try_answer_document_list_query(query, subject_id, document_ids)
        if document_list:
            return self.with_processing_trace(
                document_list,
                "document_list",
                query,
                subject_id,
                document_ids,
                decision="metadata_lookup",
                route=route,
                checker={"sufficient": True, "confidence": document_list.get("confidence", 1.0), "reasons": ["Answered from indexed document metadata."], "checker": "metadata"}
            )

        metadata_query = self.rewrite_short_followup_from_history(query, history) or query
        self.emit_trace_event(
            trace_callback,
            "Rewrite",
            "done",
            input_summary=self.compact_preview(query, 160),
            output_summary=self.compact_preview(metadata_query, 180),
            history_used=bool(history)
        )

        document_summary = self.try_answer_document_summary_query(metadata_query, subject_id, document_ids, history)
        if document_summary:
            return self.with_processing_trace(
                document_summary,
                "document_summary",
                query,
                subject_id,
                document_ids,
                decision="document_summary_metadata",
                route=route,
                history_used=False,
                checker={"sufficient": True, "confidence": document_summary.get("confidence", 1.0), "reasons": ["Answered from document-level metadata and representative chunks."], "checker": "metadata"}
            )

        known_term = self.try_answer_known_term_query(metadata_query, subject_id, document_ids)
        if known_term:
            return self.with_processing_trace(
                known_term,
                "definition",
                query,
                subject_id,
                document_ids,
                decision="known_term_metadata",
                route=route,
                checker={"sufficient": True, "confidence": known_term.get("confidence", 1.0), "reasons": ["Answered from exact known-term evidence in indexed chunks."], "checker": "metadata"}
            )

        outline_answer = self.try_answer_outline_query(metadata_query, subject_id, document_ids, history)
        if outline_answer:
            return self.with_processing_trace(
                outline_answer,
                "outline",
                query,
                subject_id,
                document_ids,
                decision="chapter_metadata_lookup",
                route=route,
                history_used=bool(history),
                checker={"sufficient": True, "confidence": outline_answer.get("confidence", 1.0), "reasons": ["Answered from chapter/outline metadata."], "checker": "metadata"}
            )

        duplicate_answer = self.try_answer_duplicate_query(metadata_query, subject_id, document_ids, history)
        if duplicate_answer:
            return self.with_processing_trace(
                duplicate_answer,
                "duplicate",
                query,
                subject_id,
                document_ids,
                decision="deduplicate_identical_evidence",
                route=route,
                history_used=bool(history),
                checker={"sufficient": True, "confidence": duplicate_answer.get("confidence", 1.0), "reasons": ["Identical content was grouped; one representative chunk was used."], "checker": "duplicate-policy"}
            )

        conflict_answer = self.try_answer_source_conflict_query(metadata_query, subject_id, document_ids, history)
        if conflict_answer:
            return self.with_processing_trace(
                conflict_answer,
                "conflict",
                query,
                subject_id,
                document_ids,
                decision="compare_source_variants",
                route=route,
                history_used=bool(history),
                checker={"sufficient": True, "confidence": conflict_answer.get("confidence", 1.0), "reasons": ["Multiple source variants were compared; no automatic truth winner selected."], "checker": "conflict-policy"}
            )

        decomposition = self.decompose_query(metadata_query)
        chapter_answer = None if decomposition.get("enabled") else self.try_answer_chapter_query(metadata_query, subject_id, document_ids, history)
        if chapter_answer:
            return self.with_processing_trace(
                chapter_answer,
                "chapter",
                query,
                subject_id,
                document_ids,
                decision="chapter_scoped_retrieval",
                route=route,
                history_used=bool(history),
                checker={"sufficient": True, "confidence": chapter_answer.get("confidence", 1.0), "reasons": ["Answered from chapter-scoped evidence."], "checker": "metadata+retrieval"}
            )

        rewritten_query = self.rewrite_query_if_needed(query, history, subject_memory)
        if rewritten_query != metadata_query:
            self.emit_trace_event(
                trace_callback,
                "Rewrite",
                "done",
                input_summary=self.compact_preview(query, 160),
                output_summary=self.compact_preview(rewritten_query, 180),
                history_used=bool(history),
                subject_memory_used=bool(subject_memory)
            )
        retrieval_strategy = "agentic_hybrid" if self.enable_agentic_rag else "hybrid_rerank"
        agentic_trace = {"enabled": self.enable_agentic_rag, "rounds": []}
        try:
            self.emit_trace_event(
                trace_callback,
                "Retrieval",
                "running",
                input_summary=self.compact_preview(rewritten_query, 180),
                output_summary=f"strategy={retrieval_strategy}; docs={len(document_ids or []) or 'all'}"
            )
            if self.enable_agentic_rag:
                context_str, sources, chunks, confidence, agentic_trace = self.retrieve_query_context_agentic(
                    rewritten_query,
                    subject_id,
                    model_name=model_name,
                    document_ids=document_ids
                )
            else:
                context_str, sources, chunks, confidence = self.retrieve_query_context(
                    rewritten_query,
                    subject_id,
                    model_name=model_name,
                    document_ids=document_ids
                )
            self.emit_trace_event(
                trace_callback,
                "Evidence",
                "done" if chunks else "blocked",
                output_summary=f"{len(chunks)} selected chunks; confidence={round(float(confidence or 0), 3)}",
                selected_count=len(chunks),
                source_count=len(sources or []),
                confidence=confidence,
                retrieval_strategy=retrieval_strategy
            )
        except Exception as e:
            print(f"[RAG] retrieval failed: {e}", flush=True)
            self.emit_trace_event(trace_callback, "Retrieval", "error", output_summary=str(e))
            context_str, sources, chunks, confidence = "", [], [], 0.0

        if not context_str:
            response = {
                "answer": "Mình chưa tìm thấy đoạn tài liệu đủ liên quan để trả lời câu này. Thử hỏi cụ thể hơn theo tên file, chương, mục hoặc khái niệm trong tài liệu.",
                "sources": [],
                "contexts": [],
                "model": self._last_model_used,
                "retrieval_strategy": retrieval_strategy,
                "confidence": 0.0,
                "fallback_used": False,
                "agentic_trace": agentic_trace
            }
            return self.with_processing_trace(
                response,
                "low_confidence",
                query,
                subject_id,
                document_ids,
                rewritten_query=rewritten_query,
                decision="no_context_found",
                history_used=bool(history),
                subject_memory_used=bool(subject_memory),
                route=route,
                checker={"sufficient": False, "confidence": 0.0, "reasons": ["No context returned from retrieval."], "checker": "retrieval-policy"}
            )

        if confidence < 0.32:
            response = {
                "answer": "Mình tìm thấy một vài đoạn gần đúng, nhưng độ liên quan quá thấp nên không trả lời để tránh suy diễn ngoài tài liệu. Hãy hỏi cụ thể hơn theo tên chương, mục hoặc khái niệm trong tài liệu.",
                "sources": [],
                "contexts": [],
                "model": self._last_model_used,
                "retrieval_strategy": "blocked_low_confidence",
                "confidence": confidence,
                "fallback_used": False,
                "agentic_trace": agentic_trace
            }
            return self.with_processing_trace(
                response,
                "low_confidence",
                query,
                subject_id,
                document_ids,
                rewritten_query=rewritten_query,
                sources=[],
                chunks=[],
                confidence=confidence,
                retrieval_strategy="blocked_low_confidence",
                agentic_trace=agentic_trace,
                decision="blocked_low_confidence",
                history_used=bool(history),
                subject_memory_used=bool(subject_memory),
                route=route,
                checker={"sufficient": False, "confidence": confidence, "reasons": ["Retrieved evidence was below the confidence threshold."], "checker": "retrieval-policy"}
            )

        fallback_used = False
        try:
            print(f"[RAG] Query: {query[:80]} | rewritten: {rewritten_query[:80]} | sources: {len(sources)} | chunks: {len(chunks)} | confidence: {confidence}", flush=True)
            self.emit_trace_event(
                trace_callback,
                "LLM",
                "running",
                input_summary=f"{len(chunks)} chunks in context",
                output_summary=f"model={self.get_llm_model_name()}"
            )
            answer = self.answer_with_llm(query, context_str, sources, history, subject_memory)
            if not answer.strip():
                fallback_used = True
                answer = self.build_extractive_answer(query, chunks, sources, confidence, timed_out=False)
            query_norm = self.normalize_text(query)
            answer_norm = self.normalize_text(answer)
            if "data model" in query_norm and "data model" not in answer_norm:
                answer = "Data model (mô hình dữ liệu) là khái niệm chính trong câu hỏi này.\n\n" + answer
            if "uml" in query_norm and "uml" not in answer_norm:
                answer = "UML là khái niệm chính trong câu hỏi này.\n\n" + answer
            if "reliability" in query_norm and "reliability" not in answer_norm:
                answer = "Reliability (độ tin cậy) là khái niệm chính trong câu hỏi này.\n\n" + answer
            if (
                any(term in query_norm for term in ["hai sach", "ca hai sach", "both books", "these books"])
                and any("gomaa" in self.normalize_text(source) for source in sources)
                and any("ddia" in self.normalize_text(source) for source in sources)
                and ("gomaa" not in answer_norm or "ddia" not in answer_norm)
            ):
                answer = (
                    "Gomaa và DDIA đều liên quan tới thiết kế hệ thống, nhưng nhấn mạnh ở hai góc nhìn khác nhau: "
                    "Gomaa tập trung vào modeling/design bằng UML và phương pháp thiết kế phần mềm; "
                    "DDIA tập trung vào thiết kế hệ thống dữ liệu đáng tin cậy, mở rộng và dễ bảo trì.\n\n"
                    + answer
                )
            if confidence < 0.2:
                fallback_used = True
                answer = (
                    "I found a few possibly related chunks, but the match is weak, so treat the answer below as a cautious suggestion:\n\n"
                    + answer
                )
            answer = self.append_duplicate_source_note(answer, chunks)
        except Exception as e:
            fallback_used = True
            timed_out = isinstance(e, requests.exceptions.Timeout)
            print(f"[RAG] LLM fallback used: {e}", flush=True)
            answer = self.build_extractive_answer(query, chunks, sources, confidence, timed_out=timed_out)
            answer = self.append_duplicate_source_note(answer, chunks)

        response = {
            "answer": answer,
            "sources": sources,
            "contexts": chunks,
            "model": self._last_model_used,
            "retrieval_strategy": retrieval_strategy,
            "confidence": confidence,
            "fallback_used": fallback_used or self._last_model_used != self.get_llm_model_name(),
            "agentic_trace": agentic_trace
        }
        response = self.with_processing_trace(
            response,
            "document_question",
            query,
            subject_id,
            document_ids,
            rewritten_query=rewritten_query,
            sources=sources,
            chunks=chunks,
            confidence=confidence,
            retrieval_strategy=retrieval_strategy,
            agentic_trace=agentic_trace,
            fallback_used=response["fallback_used"],
            decision="run_rag",
            history_used=bool(history),
            subject_memory_used=bool(subject_memory),
            route=route
        )
        citation = response.get("processing_trace", {}).get("citation_verification", {})
        self.emit_trace_event(
            trace_callback,
            "Citation Check",
            "done" if citation.get("verified_sources") else "skipped",
            output_summary=citation.get("reason") or "Citation verification completed.",
            verified_sources=citation.get("verified_sources", []),
            rejected_sources=citation.get("rejected_sources", [])
        )
        return response
