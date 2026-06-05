import math
import os
import re
import time
import unicodedata
from collections import Counter, defaultdict

import chromadb
import requests
from jinja2 import Template
from langchain_huggingface import HuggingFaceEmbeddings


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
        self.candidate_pool = int(os.getenv("RAG_CANDIDATE_POOL", "20"))
        self.rerank_top_k = int(os.getenv("RAG_RERANK_TOP_K", "6"))
        self.max_context_chars = int(os.getenv("RAG_MAX_CONTEXT_CHARS", "5000"))
        self.ollama_num_ctx = int(os.getenv("OLLAMA_NUM_CTX", "4096"))
        self.ollama_num_predict = int(os.getenv("OLLAMA_NUM_PREDICT", "512"))
        self.ollama_timeout = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "10"))
        self.ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
        self.enable_reranker = os.getenv("RAG_ENABLE_RERANKER", "false").lower() == "true"
        self.reranker_model_name = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")

        prompt_path = os.path.join(os.path.dirname(__file__), "..", "prompts", "system_prompt.jinja")
        with open(prompt_path, "r", encoding="utf-8") as f:
            self.prompt_template = Template(f.read())

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

    def build_scope_filter(self, subject_id, document_ids=None):
        allowed_ids = self.normalize_document_ids(document_ids)
        if allowed_ids:
            return {"document_id": {"$in": allowed_ids}}
        return {"subject_id": subject_id}

    def get_embedding_model(self, model_name="intfloat/multilingual-e5-base"):
        if model_name not in self.embeddings:
            print(f"Loading embedding model: {model_name}...", flush=True)
            self.embeddings[model_name] = HuggingFaceEmbeddings(model_name=model_name)
        return self.embeddings[model_name]

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
        fallback_model = os.getenv("OLLAMA_FALLBACK_MODEL", "gemma3:4b").strip()
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
        prompt = self.prepare_llm_prompt(prompt)
        primary_model = self.get_llm_model_name()

        try:
            self._last_model_used = primary_model
            return self.invoke_ollama_model(primary_model, prompt)
        except Exception as primary_error:
            self._primary_llm_unavailable = True
            fallback_model = os.getenv("OLLAMA_FALLBACK_MODEL", "gemma3:4b").strip()
            if not fallback_model or isinstance(primary_error, requests.exceptions.Timeout):
                raise primary_error
            print(f"[RAG] primary model failed ({primary_model}); using fallback {fallback_model}: {primary_error}", flush=True)
            self._last_model_used = fallback_model
            return self.invoke_ollama_model(fallback_model, prompt)

    def invoke_ollama_model(self, model, prompt):
        response = requests.post(
            f"{self.ollama_base_url}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": float(os.getenv("LLM_TEMPERATURE", "0.2")),
                    "num_ctx": self.ollama_num_ctx,
                    "num_predict": self.ollama_num_predict
                }
            },
            timeout=self.ollama_timeout
        )
        response.raise_for_status()
        return self.clean_llm_output(response.json().get("response", ""))

    def clean_llm_output(self, text):
        text = str(text or "").strip()
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
        return text.strip()

    def prepare_llm_prompt(self, prompt):
        prompt = str(prompt or "").strip()
        if self.get_llm_model_name().lower().startswith("qwen3") and not prompt.startswith("/no_think"):
            return "/no_think\n" + prompt
        return prompt

    def get_llm_provider(self):
        return "ollama"

    def get_llm_model_name(self):
        return os.getenv("OLLAMA_MODEL", "qwen3:4b").strip()

    def describe_llm(self):
        fallback = os.getenv("OLLAMA_FALLBACK_MODEL", "gemma3:4b").strip()
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
            return str(chunk.get("text", "")).strip(), {
                "page_number": chunk.get("page_number") or 0,
                "slide_number": chunk.get("slide_number") or 0,
                "heading": str(chunk.get("heading") or "")[:240],
                "local_index": int(chunk.get("local_index") or 0)
            }

        return str(chunk or "").strip(), {
            "page_number": 0,
            "slide_number": 0,
            "heading": "",
            "local_index": 0
        }

    def embed_and_store(self, chunks, subject_id, document_name, document_id, model_name="intfloat/multilingual-e5-base"):
        embedder = self.get_embedding_model(model_name)
        document_id = str(document_id)

        try:
            existing = self.collection.get(where={"document_id": document_id})
            if existing and existing.get("ids"):
                self.collection.delete(ids=existing["ids"])
                print(f"  Deleted {len(existing['ids'])} old chunks for: {document_id}", flush=True)
        except Exception:
            pass

        documents, metadatas, ids = [], [], []
        for i, chunk in enumerate(chunks):
            text, extra_meta = self.chunk_text_and_metadata(chunk)
            if len(text) < 20:
                continue
            chunk_id = f"{document_id}_chunk{i}"
            metadata = {
                "subject_id": subject_id,
                "document_name": document_name,
                "document_id": document_id,
                "chunk_index": i,
                "chunk_length": len(text)
            }
            metadata.update(extra_meta)
            documents.append(text)
            metadatas.append(metadata)
            ids.append(chunk_id)

        if not documents:
            return 0

        print(f"  Embedding {len(documents)} chunks...", flush=True)
        start = time.time()
        embeddings_list = []
        batch_size = int(os.getenv("EMBEDDING_BATCH_SIZE", "64"))
        total = len(documents)
        for batch_start in range(0, total, batch_size):
            batch_end = min(batch_start + batch_size, total)
            embeddings_list.extend(embedder.embed_documents(documents[batch_start:batch_end]))
            print(
                f"  Embedded {batch_end}/{total} chunks ({batch_end * 100 // total}%) in {time.time() - start:.1f}s",
                flush=True
            )

        self.collection.add(
            embeddings=embeddings_list,
            documents=documents,
            metadatas=metadatas,
            ids=ids
        )
        print(f"  Embedding + ChromaDB store done in {time.time() - start:.1f}s", flush=True)
        return len(documents)

    def delete_document(self, document_id):
        existing = self.collection.get(where={"document_id": str(document_id)})
        ids = existing.get("ids", []) if existing else []
        if ids:
            self.collection.delete(ids=ids)
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
                "id": ids[index] if index < len(ids) else f"{document_id}_chunk{index}",
                "text": documents[index] if index < len(documents) else "",
                "metadata": metadata,
                "embedding_dimensions": len(embedding),
                "embedding_preview": [round(float(value), 6) for value in embedding[:12]]
            })
        rows.sort(key=lambda row: int(row["metadata"].get("chunk_index", 0)))
        return {
            "document_id": str(result_id),
            "total": len(rows),
            "offset": safe_offset,
            "limit": safe_limit,
            "chunks": rows[safe_offset:safe_offset + safe_limit]
        }

    def normalize_text(self, value):
        text = str(value or "").lower()
        text = unicodedata.normalize("NFD", text)
        text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
        text = re.sub(r"\.(pdf|docx|pptx|ppt)\b", " ", text)
        text = re.sub(r"[_\-]+", " ", text)
        text = re.sub(r"[^a-z0-9\s]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    def tokenize(self, value):
        stopwords = {
            "la", "gi", "co", "cua", "cac", "nhung", "mot", "nay", "kia",
            "trong", "ve", "cho", "toi", "minh", "hay", "neu", "thi", "va",
            "the", "nao", "duoc", "khong", "file", "pdf", "tai", "lieu",
            "mon", "chuong", "chapter", "please", "what", "how", "many"
        }
        return [
            term for term in self.normalize_text(value).split()
            if len(term) >= 3 and term not in stopwords
        ]

    def get_ordered_subject_chunks(self, subject_id, document_ids=None):
        try:
            result = self.collection.get(
                where=self.build_scope_filter(subject_id, document_ids),
                include=["documents", "metadatas"]
            )
            rows = []
            ids = result.get("ids", [])
            for i, (doc, meta) in enumerate(zip(result.get("documents", []), result.get("metadatas", []))):
                rows.append({
                    "id": ids[i] if i < len(ids) else f"{meta.get('document_id', 'unknown')}_{i}",
                    "content": doc,
                    "metadata": meta,
                    "dense_similarity": 0.0,
                    "keyword_score": 0.0,
                    "rrf_score": 0.0,
                    "rerank_score": 0.0
                })
            return sorted(rows, key=lambda row: (
                str(row["metadata"].get("document_id", "")),
                int(row["metadata"].get("chunk_index", 0))
            ))
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
        heading = str(metadata.get("heading") or "").strip()
        if page:
            parts.append(f"page {page}")
        if slide:
            parts.append(f"slide {slide}")
        if heading:
            parts.append(heading[:90])
        return " | ".join(parts)

    def build_manual_context(self, rows):
        context_parts, sources, chunks = [], set(), []
        total_chars = 0
        for row in rows:
            meta = row["metadata"]
            content = row["content"]
            label = self.format_source_label(meta)
            addition = f"[Source: {label}]\n{content}"
            if total_chars + len(addition) > self.max_context_chars:
                break
            total_chars += len(addition)
            context_parts.append(addition)
            sources.add(meta.get("document_name", "unknown"))
            chunks.append({
                "content": content[:260],
                "source": meta.get("document_name", "unknown"),
                "similarity": round(float(row.get("dense_similarity") or row.get("rerank_score") or 1), 4),
                "chunk_index": meta.get("chunk_index", 0),
                "page_number": meta.get("page_number", 0),
                "slide_number": meta.get("slide_number", 0),
                "heading": meta.get("heading", "")
            })
        return "\n\n".join(context_parts), list(sources), chunks

    def build_extractive_answer(self, query, chunks, sources, confidence=0.0, timed_out=False):
        if not chunks:
            return "Minh tim duoc nguon lien quan nhung chua trich duoc doan du ro de tra loi. Hay hoi cu the hon theo ten chuong, muc hoac khai niem."

        intro = "Minh tra loi nhanh dua tren cac doan tai lieu tim duoc"
        if timed_out:
            intro += " vi AI local mat qua lau de tong hop"
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
            lines.append("Äá»™ khá»›p chÆ°a cao, nÃªn pháº§n trÃªn nÃªn xem nhÆ° Ä‘oáº¡n gáº§n nháº¥t chá»© chÆ°a cháº¯c lÃ  cÃ¢u tráº£ lá»i cuá»‘i cÃ¹ng.")
        if sources:
            lines.append("")
            lines.append("Nguon: " + ", ".join(sources[:4]))
        return "\n".join(lines)

    def try_answer_system_or_out_of_scope_query(self, query):
        normalized = self.normalize_text(query)
        greeting_terms = ["hello", "hi", "helo", "xin chao", "chao", "chao ban"]
        if normalized in greeting_terms:
            return {
                "answer": "Chao ban. Minh co the tra loi cac cau hoi dua tren tai lieu da index trong mon hoc hien tai.",
                "sources": [],
                "contexts": [],
                "model": "direct",
                "retrieval_strategy": "direct_greeting",
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
            answer = "Khong the chia cho 0." if value is None else f"{arithmetic_match.group(0)} = {int(value) if value.is_integer() else value}."
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
                "answer": "Cau nay nam ngoai pham vi tai lieu cua mon hoc hien tai. Minh chi tra loi cac cau hoi dua tren tai lieu da index, hoac cac cau hoi thao tac he thong cua EduChatbot.",
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
                "answer": f"Minh la EduChatbot AI. Phan tra loi dang dung {self.describe_llm()}; phan tim tai lieu dung embedding **intfloat/multilingual-e5-base** va retrieval local.",
                "sources": [],
                "contexts": [],
                "model": self._last_model_used,
                "retrieval_strategy": "system",
                "confidence": 1.0,
                "fallback_used": False
            }
        return None

    def is_clear_out_of_scope_query(self, normalized):
        out_of_scope_terms = [
            "hom nay thu may", "ngay may", "may gio", "thoi tiet", "weather",
            "tin tuc", "news", "gia vang", "gia bitcoin", "ti gia",
            "mua laptop", "nen mua", "tu van mua", "shopping",
            "viet code", "lap trinh giup", "fix code", "debug code",
            "chien tranh", "lich su the gioi", "bong da", "the thao",
            "nau an", "cong thuc nau", "du lich", "dat ve"
        ]
        return any(term in normalized for term in out_of_scope_terms)

    def try_answer_document_list_query(self, query, subject_id, document_ids=None):
        normalized = self.normalize_text(query)
        list_terms = [
            "hien co tai lieu", "co tai lieu", "danh sach tai lieu",
            "cac tai lieu", "cac nguon", "nguon nao", "file nao",
            "documents", "sources", "which files"
        ]
        if not any(term in normalized for term in list_terms):
            return None
        rows = self.get_ordered_subject_chunks(subject_id, document_ids)
        if not rows:
            return {
                "answer": "Hien mon nay chua co tai lieu nao da index xong.",
                "sources": [],
                "contexts": [],
                "model": self._last_model_used,
                "retrieval_strategy": "document_list",
                "confidence": 1.0,
                "fallback_used": False
            }
        doc_names, grouped = self.group_by_document(rows)
        lines = ["Trong mÃ´n hiá»‡n táº¡i, AI Ä‘ang cÃ³ cÃ¡c nguá»“n Ä‘Ã£ index:", ""]
        for index, name in enumerate(doc_names, 1):
            lines.append(f"{index}. **{name}** ({len(grouped[name])} chunks)")
        return {
            "answer": "\n".join(lines),
            "sources": doc_names,
            "contexts": [],
            "model": self._last_model_used,
            "retrieval_strategy": "document_list",
            "confidence": 1.0,
            "fallback_used": False
        }

    def is_outline_query(self, query):
        normalized = self.normalize_text(query)
        return any(term in normalized for term in [
            "cac chuong", "danh sach chuong", "liet ke chuong", "muc luc",
            "co may chuong", "bao nhieu chuong", "so chuong",
            "chapters", "chapter list", "number of chapter", "table of contents"
        ])

    def try_answer_outline_query(self, query, subject_id, document_ids=None):
        if not self.is_outline_query(query):
            return None
        rows = self.get_ordered_subject_chunks(subject_id, document_ids)
        if not rows:
            return None
        selected = []
        for row in rows:
            text = self.normalize_text(f"{row['metadata'].get('heading', '')} {row['content'][:900]}")
            if any(term in text for term in ["contents", "table of contents", "chapter", "chuong", "muc luc"]):
                selected.append(row)
            if len(selected) >= 12:
                break
        if not selected:
            selected = rows[:10]
        context_str, sources, chunks = self.build_manual_context(selected)
        answer = self.build_outline_answer(selected, sources)

        return {
            "answer": answer,
            "sources": sources,
            "contexts": chunks,
            "model": self._last_model_used,
            "retrieval_strategy": "outline_structured",
            "confidence": 0.85 if selected else 0.45,
            "fallback_used": False
        }

    def build_outline_answer(self, rows, sources):
        chapter_pattern = re.compile(r"\b(chapter|chuong)\s+([0-9]+)\b[:.\-\s]*(.{0,90})", re.IGNORECASE)
        found = {}
        for row in rows:
            heading = str(row["metadata"].get("heading") or "")
            text = f"{heading}\n{row['content'][:1500]}"
            for match in chapter_pattern.finditer(text):
                number = int(match.group(2))
                title = re.sub(r"\s+", " ", match.group(3)).strip(" :-\t\r\n")
                if number not in found:
                    found[number] = title

        if found:
            lines = [f"Minh tim thay it nhat **{len(found)} chuong** trong tai lieu:", ""]
            for number in sorted(found):
                title = found[number]
                lines.append(f"- Chuong {number}" + (f": {title}" if title else ""))
        else:
            lines = [
                "Minh chua thay muc luc/chapter list du ro trong cac chunk da index.",
                "Cac doan gan nhat co nhac toi chuong hoac muc luc da duoc dung lam nguon tham khao."
            ]
        if sources:
            lines.extend(["", "Nguon: " + ", ".join(sources[:4])])
        return "\n".join(lines)

    def dense_candidates(self, query, subject_id, model_name, document_ids=None):
        start = time.time()
        if self.collection.count() == 0:
            return []
        embedder = self.get_embedding_model(model_name)
        query_embedding = embedder.embed_query(query)
        n_results = min(max(self.candidate_pool, self.rerank_top_k), self.collection.count())
        result = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where=self.build_scope_filter(subject_id, document_ids),
            include=["documents", "metadatas", "distances"]
        )
        candidates = []
        docs = result.get("documents", [[]])[0] if result.get("documents") else []
        metas = result.get("metadatas", [[]])[0] if result.get("metadatas") else []
        distances = result.get("distances", [[]])[0] if result.get("distances") else []
        ids = result.get("ids", [[]])[0] if result.get("ids") else []
        for rank, doc in enumerate(docs):
            distance = distances[rank] if rank < len(distances) else 1
            candidates.append({
                "id": ids[rank] if rank < len(ids) else f"dense_{rank}",
                "content": doc,
                "metadata": metas[rank],
                "dense_similarity": round(1 - distance, 4),
                "dense_rank": rank + 1,
                "keyword_rank": None,
                "keyword_score": 0.0,
                "rrf_score": 0.0,
                "rerank_score": 0.0
            })
        print(f"[RAG] vector search {len(candidates)} candidates in {time.time() - start:.2f}s", flush=True)
        return candidates

    def keyword_candidates(self, query, rows):
        start = time.time()
        query_terms = self.tokenize(query)
        if not query_terms:
            return []
        docs_tokens = [self.tokenize(f"{row['metadata'].get('document_name', '')} {row['metadata'].get('heading', '')} {row['content']}") for row in rows]
        doc_freq = Counter(term for tokens in docs_tokens for term in set(tokens))
        total_docs = max(len(rows), 1)
        scored = []
        for row, tokens in zip(rows, docs_tokens):
            counts = Counter(tokens)
            score = 0.0
            for term in query_terms:
                if counts[term] <= 0:
                    continue
                idf = math.log((total_docs - doc_freq[term] + 0.5) / (doc_freq[term] + 0.5) + 1)
                score += counts[term] * idf
            if score > 0:
                clone = dict(row)
                clone["keyword_score"] = round(score, 4)
                scored.append(clone)
        scored.sort(key=lambda row: -row["keyword_score"])
        for rank, row in enumerate(scored):
            row["keyword_rank"] = rank + 1
        print(f"[RAG] keyword search {len(scored[:self.candidate_pool])} candidates in {time.time() - start:.2f}s", flush=True)
        return scored[:self.candidate_pool]

    def reciprocal_rank_fusion(self, dense_rows, keyword_rows):
        fused = {}
        for source_rows, rank_key in [(dense_rows, "dense_rank"), (keyword_rows, "keyword_rank")]:
            for index, row in enumerate(source_rows):
                item = fused.setdefault(row["id"], dict(row))
                rank = row.get(rank_key) or index + 1
                item["rrf_score"] = item.get("rrf_score", 0.0) + 1.0 / (60 + rank)
                item["dense_similarity"] = max(item.get("dense_similarity", 0.0), row.get("dense_similarity", 0.0))
                item["keyword_score"] = max(item.get("keyword_score", 0.0), row.get("keyword_score", 0.0))
        rows = list(fused.values())
        rows.sort(key=lambda row: -row["rrf_score"])
        return rows[:self.candidate_pool]

    def rerank_candidates(self, query, candidates):
        if not candidates:
            return []
        start = time.time()
        if not self.enable_reranker:
            candidates.sort(key=lambda row: -row["rrf_score"])
            print(f"[RAG] reranker disabled; using RRF only in {time.time() - start:.2f}s", flush=True)
            return candidates[:self.rerank_top_k]
        try:
            pairs = [[query, row["content"]] for row in candidates]
            scores = self.get_reranker().predict(pairs)
            for row, score in zip(candidates, scores):
                row["rerank_score"] = float(score)
            candidates.sort(key=lambda row: -row["rerank_score"])
            print(f"[RAG] rerank {len(candidates)} candidates in {time.time() - start:.2f}s", flush=True)
            return candidates
        except Exception as e:
            print(f"[RAG] reranker unavailable, using RRF only: {e}", flush=True)
            candidates.sort(key=lambda row: -row["rrf_score"])
            return candidates

    def select_context(self, ranked_rows):
        if not ranked_rows:
            return "", [], [], 0.0
        top_rows = ranked_rows[:self.rerank_top_k]
        max_score = max(row.get("rerank_score", 0.0) for row in top_rows)
        min_score = min(row.get("rerank_score", 0.0) for row in top_rows)
        score_span = max(max_score - min_score, 1e-6)
        selected, per_doc = [], defaultdict(int)
        for row in top_rows:
            doc_name = row["metadata"].get("document_name", "unknown")
            if per_doc[doc_name] >= 4:
                continue
            row["confidence_score"] = (row.get("rerank_score", 0.0) - min_score) / score_span if score_span else row.get("dense_similarity", 0.0)
            selected.append(row)
            per_doc[doc_name] += 1
        context, sources, chunks = self.build_manual_context(selected)
        confidence = max(
            max((row.get("confidence_score", 0.0) for row in selected), default=0.0),
            max((row.get("dense_similarity", 0.0) for row in selected), default=0.0)
        )
        return context, sources, chunks, round(min(confidence, 1.0), 4)

    def retrieve_query_context(self, query, subject_id, model_name="intfloat/multilingual-e5-base", document_ids=None):
        rows = self.get_ordered_subject_chunks(subject_id, document_ids)
        if not rows:
            return "", [], [], 0.0
        dense = self.dense_candidates(query, subject_id, model_name, document_ids)
        keyword = self.keyword_candidates(query, rows)
        fused = self.reciprocal_rank_fusion(dense, keyword)
        ranked = self.rerank_candidates(query, fused)
        return self.select_context(ranked)

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
        normalized = self.normalize_text(query)
        if not history:
            return False
        return len(normalized.split()) <= 6 or any(term in normalized for term in [
            "no", "do", "nay", "kia", "chi tiet hon", "giai thich them", "tiep", "why", "more"
        ])

    def rewrite_query_if_needed(self, query, history=None, subject_memory=""):
        if not self.should_rewrite_query(query, history or []):
            return query
        history_text = self.format_history(history or [], max_messages=6)
        memory_text = (subject_memory or "").strip()[:2000]
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
- You may infer relationships between retrieved facts, but mark inferred comments as "Nhan xet suy ra" or "Inferred note".
- Cite source file names naturally. Include page/slide when the source label provides it.
- If the context is weak, say what is missing and show the closest useful source.
""".strip()
        full_prompt = f"{prompt}{memory_block}{history_block}\n\n{synthesis_rules}\n\nQuestion: {query}\nAnswer:"
        start = time.time()
        answer = self.invoke_llm(full_prompt).strip()
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
            answer = self.invoke_llm(retry_prompt).strip()
        return answer

    def generate_answer(self, query, subject_id, model_name="intfloat/multilingual-e5-base", history=None, document_ids=None, subject_memory=""):
        system_answer = self.try_answer_system_or_out_of_scope_query(query)
        if system_answer:
            return system_answer

        document_list = self.try_answer_document_list_query(query, subject_id, document_ids)
        if document_list:
            return document_list

        outline_answer = self.try_answer_outline_query(query, subject_id, document_ids)
        if outline_answer:
            return outline_answer

        rewritten_query = self.rewrite_query_if_needed(query, history, subject_memory)
        try:
            context_str, sources, chunks, confidence = self.retrieve_query_context(
                rewritten_query,
                subject_id,
                model_name=model_name,
                document_ids=document_ids
            )
        except Exception as e:
            print(f"[RAG] retrieval failed: {e}", flush=True)
            context_str, sources, chunks, confidence = "", [], [], 0.0

        if not context_str:
            return {
                "answer": "Minh chua tim thay doan tai lieu du lien quan de tra loi cau nay. Thu hoi cu the hon theo ten file, chuong, muc hoac khai niem trong tai lieu.",
                "sources": [],
                "contexts": [],
                "model": self._last_model_used,
                "retrieval_strategy": "hybrid_rerank",
                "confidence": 0.0,
                "fallback_used": False
            }

        if confidence < 0.18:
            return {
                "answer": "Minh tim thay mot vai doan gan dung, nhung do lien quan qua thap nen khong tra loi de tranh suy dien ngoai tai lieu. Hay hoi cu the hon theo ten chuong, muc hoac khai niem trong tai lieu.",
                "sources": sources,
                "contexts": chunks,
                "model": self._last_model_used,
                "retrieval_strategy": "blocked_low_confidence",
                "confidence": confidence,
                "fallback_used": False
            }

        fallback_used = False
        try:
            print(f"[RAG] Query: {query[:80]} | rewritten: {rewritten_query[:80]} | sources: {len(sources)} | chunks: {len(chunks)} | confidence: {confidence}", flush=True)
            answer = self.answer_with_llm(query, context_str, sources, history, subject_memory)
            if not answer.strip():
                fallback_used = True
                answer = self.build_extractive_answer(query, chunks, sources, confidence, timed_out=False)
            if confidence < 0.2:
                fallback_used = True
                answer = (
                    "MÃ¬nh tÃ¬m Ä‘Æ°á»£c má»™t vÃ i Ä‘oáº¡n cÃ³ thá»ƒ liÃªn quan, nhÆ°ng Ä‘á»™ khá»›p chÆ°a cao nÃªn cÃ¢u tráº£ lá»i dÆ°á»›i Ä‘Ã¢y cáº§n Ä‘Æ°á»£c xem nhÆ° gá»£i Ã½:\n\n"
                    + answer
                )
        except Exception as e:
            fallback_used = True
            timed_out = isinstance(e, requests.exceptions.Timeout)
            print(f"[RAG] LLM fallback used: {e}", flush=True)
            answer = self.build_extractive_answer(query, chunks, sources, confidence, timed_out=timed_out)

        return {
            "answer": answer,
            "sources": sources,
            "contexts": chunks,
            "model": self._last_model_used,
            "retrieval_strategy": "hybrid_rerank",
            "confidence": confidence,
            "fallback_used": fallback_used or self._last_model_used != self.get_llm_model_name()
        }
