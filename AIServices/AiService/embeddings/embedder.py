"""Embedding model manager for query and document vectors."""

from langchain_huggingface import HuggingFaceEmbeddings

from utils.text_normalization import normalize_text


class EmbeddingManager:
    def __init__(self, default_model_name: str, device: str = "cuda"):
        self.default_model_name = default_model_name
        self.device = device
        self._models = {}
        self._query_cache = {}

    def get_model(self, model_name=None):
        model_name = model_name or self.default_model_name
        if model_name not in self._models:
            print(f"Loading embedding model: {model_name} on {self.device}...", flush=True)
            self._models[model_name] = HuggingFaceEmbeddings(
                model_name=model_name,
                model_kwargs={"device": self.device},
                encode_kwargs={"normalize_embeddings": True},
            )
        return self._models[model_name]

    def embed_documents(self, texts, model_name=None):
        return self.get_model(model_name).embed_documents(texts)

    def embed_query(self, text, model_name=None):
        return self.get_model(model_name).embed_query(text)

    def embed_query_cached(self, query, model_name=None):
        model_name = model_name or self.default_model_name
        normalized_query = normalize_text(query)
        cache_key = f"{model_name}|{normalized_query}"
        if cache_key not in self._query_cache:
            self._query_cache[cache_key] = self.embed_query(query, model_name)
        return self._query_cache[cache_key]

    def clear_cache(self):
        self._query_cache.clear()


Embedder = EmbeddingManager
