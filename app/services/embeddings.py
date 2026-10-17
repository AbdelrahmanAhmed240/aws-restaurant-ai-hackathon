"""Embeddings service exclusively using Google's official Gemini embedding API via google-genai SDK.
Model: gemini-embedding-001 (configurable via GEMINI_EMBEDDING_MODEL).
"""

from typing import List
from config import config

_gemini_client = None

def get_gemini_client():
    """Lazily initialize Google Gen AI SDK client.
    Does not crash on import or when GEMINI_API_KEY is not yet configured.
    """
    global _gemini_client
    if _gemini_client is None:
        api_key = getattr(config, "GEMINI_API_KEY", "") or ""
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is missing. Please set it in your .env file."
            )
        from google import genai
        _gemini_client = genai.Client(api_key=api_key)
    return _gemini_client

def _embed_gemini(texts: List[str]) -> List[List[float]]:
    """Embed texts using the official Google Gen AI SDK embed_content API."""
    if not texts:
        return []

    client = get_gemini_client()
    model = getattr(config, "GEMINI_EMBEDDING_MODEL", "gemini-embedding-001") or "gemini-embedding-001"

    # Batch process in clean batches of up to 50 items
    batch_size = 50
    all_embeddings: List[List[float]] = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        response = client.models.embed_content(
            model=model,
            contents=batch,
        )
        if response and response.embeddings:
            for item in response.embeddings:
                all_embeddings.append(list(item.values))
        else:
            raise RuntimeError(f"Gemini embedding API returned empty response for model {model}.")

    return all_embeddings

def embed_texts(texts: List[str]) -> List[List[float]]:
    """Generate real embeddings for multiple documents using Gemini embedding model.
    Does not fall back to other providers to avoid mixing incompatible vector spaces.
    """
    if not texts:
        return []
    return _embed_gemini(texts)

def embed_query(text: str) -> List[float]:
    """Generate a real embedding for a single user query using the same Gemini embedding model."""
    if not text or not text.strip():
        return []
    embeddings = embed_texts([text])
    return embeddings[0] if embeddings else []