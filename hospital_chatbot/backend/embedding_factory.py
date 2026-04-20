"""Embedding factory supporting both Ollama and sentence-transformers.

Default runtime is Ollama + bge-m3, but sentence-transformers remains available
as a fallback for offline debugging.
"""

from __future__ import annotations

import os
from typing import Sequence

import requests

EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "ollama").strip().lower()
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "bge-m3:latest")
SENTENCE_TRANSFORMERS_MODEL = os.getenv("SENTENCE_TRANSFORMERS_EMBED_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")
OLLAMA_TIMEOUT_SECONDS = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "60"))


class OllamaEmbeddingFunction:
    def __init__(self, base_url: str = OLLAMA_BASE_URL, model_name: str = OLLAMA_EMBED_MODEL) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name

    def _embed_api(self, texts: Sequence[str]) -> list[list[float]]:
        response = requests.post(
            f"{self.base_url}/api/embed",
            json={"model": self.model_name, "input": list(texts)},
            timeout=OLLAMA_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()
        embeds = data.get("embeddings") or []
        if not embeds:
            raise RuntimeError("Ollama /api/embed returned no embeddings")
        return embeds

    def _embeddings_api(self, texts: Sequence[str]) -> list[list[float]]:
        embeddings: list[list[float]] = []
        for text in texts:
            response = requests.post(
                f"{self.base_url}/api/embeddings",
                json={"model": self.model_name, "prompt": text},
                timeout=OLLAMA_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            data = response.json()
            emb = data.get("embedding")
            if not emb:
                raise RuntimeError("Ollama /api/embeddings returned no embedding")
            embeddings.append(emb)
        return embeddings

    # ✅ แก้ไขตรงนี้: เปลี่ยนจาก texts เป็น input ตามมาตรฐานใหม่ของ ChromaDB
    def __call__(self, input: Sequence[str]) -> list[list[float]]:
        try:
            return self._embed_api(input)
        except Exception:
            return self._embeddings_api(input)

    def name(self) -> str:
        return f"ollama::{self.model_name}"


class TyphoonEmbeddingFunction:
    """Typhoon Embedding Function (OpenAI-compatible) for Cloud Deployment."""
    def __init__(self, api_key: str | None = None, model_name: str = "pythai-sentence-bert-base-v2"):
        self.api_key = api_key or os.getenv("TYPHOON_API_KEY")
        self.model_name = model_name
        self.base_url = "https://api.opentyphoon.ai/v1"

    def __call__(self, input: Sequence[str]) -> list[list[float]]:
        if not self.api_key:
            raise RuntimeError("TYPHOON_API_KEY is not set.")
        
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("Please install 'openai' library to use Typhoon embeddings.")

        client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        response = client.embeddings.create(
            input=list(input),
            model=self.model_name
        )
        return [data.embedding for data in response.data]

    def name(self) -> str:
        return f"typhoon::{self.model_name}"


def build_embedding_function(provider: str | None = None, *, model_name: str | None = None):
    provider = (provider or EMBEDDING_PROVIDER).strip().lower()
    if provider == "ollama":
        return OllamaEmbeddingFunction(model_name=model_name or OLLAMA_EMBED_MODEL)
    if provider == "typhoon":
        return TyphoonEmbeddingFunction(model_name=model_name or "pythai-sentence-bert-base-v2")
    if provider in {"sentence-transformers", "sentence_transformers", "hf"}:
        from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

        return SentenceTransformerEmbeddingFunction(model_name=model_name or SENTENCE_TRANSFORMERS_MODEL)
    raise ValueError(f"Unsupported EMBEDDING_PROVIDER: {provider}")