import os
from sentence_transformers import SentenceTransformer
from llama_index.core.embeddings import BaseEmbedding
from pydantic.v1 import PrivateAttr
from ...setting import RAGSettings


class _SentenceTransformerEmbedding(BaseEmbedding):
    _model: SentenceTransformer = PrivateAttr()
    _batch_size: int = PrivateAttr(default=32)

    def __init__(self, model_name: str, cache_folder: str | None = None, batch_size: int = 32):
        super().__init__()
        self._model = SentenceTransformer(model_name, cache_folder=cache_folder)
        self._batch_size = batch_size

    # llama-index 0.10 expects these protected methods (BaseEmbedding is abstract)
    def _get_text_embedding(self, text: str):
        return self._model.encode(text, normalize_embeddings=True).tolist()

    def _get_query_embedding(self, query: str):
        return self._get_text_embedding(query)

    async def _aget_query_embedding(self, query: str):
        return self._get_query_embedding(query)

    def _get_text_embedding_batch(self, texts: list[str], **kwargs):
        return self._model.encode(
            texts,
            normalize_embeddings=True,
            batch_size=self._batch_size,
        ).tolist()

    def _get_query_embedding_batch(self, queries: list[str], **kwargs):
        return self._get_text_embedding_batch(queries)

    async def _aget_text_embedding(self, text: str):
        return self._get_text_embedding(text)

    async def _aget_text_embedding_batch(self, texts: list[str], **kwargs):
        return self._get_text_embedding_batch(texts, **kwargs)

    async def _aget_query_embedding_batch(self, queries: list[str], **kwargs):
        return self._get_query_embedding_batch(queries, **kwargs)

    # Backwards compat for any callers using these names
    def get_text_embeddings(self, texts: list[str]):
        return self._get_text_embedding_batch(texts)


class LocalEmbedding:
    @staticmethod
    def set(setting: RAGSettings | None = None, **kwargs):
        setting = setting or RAGSettings()
        model_name = setting.ingestion.embed_llm
        cache_folder = os.path.join(os.getcwd(), setting.ingestion.cache_folder)
        return _SentenceTransformerEmbedding(
            model_name=model_name,
            cache_folder=cache_folder,
            batch_size=setting.ingestion.embed_batch_size,
        )

    @staticmethod
    def pull(host: str, **kwargs):
        raise NotImplementedError("Embedding model pulling is not supported (Ollama removed).")

    @staticmethod
    def check_model_exist(host: str, **kwargs) -> bool:
        return False
