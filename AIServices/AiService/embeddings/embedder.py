"""Embedding facade for query and document vectors."""

from langchain_huggingface import HuggingFaceEmbeddings


class Embedder:
    def __init__(self, model_name: str, device: str = "cuda"):
        self.model_name = model_name
        self.device = device
        self._model = None

    @property
    def model(self):
        if self._model is None:
            self._model = HuggingFaceEmbeddings(
                model_name=self.model_name,
                model_kwargs={"device": self.device},
                encode_kwargs={"normalize_embeddings": True},
            )
        return self._model

    def embed_documents(self, texts):
        return self.model.embed_documents(texts)

    def embed_query(self, text: str):
        return self.model.embed_query(text)
