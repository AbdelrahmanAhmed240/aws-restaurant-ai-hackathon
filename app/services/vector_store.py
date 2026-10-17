import os
import re
from typing import Dict, List

from config import config
from app.services.embeddings import embed_query, embed_texts

_client = None
_collection = None
_IMPORT_ERROR = None

def _import_chromadb():
    global _IMPORT_ERROR
    try:
        # Lazy import prevents web server boot failure if chromadb or its C++ dependencies have runtime issues
        import chromadb
        from chromadb.config import Settings
        return chromadb, Settings
    except Exception as exc:
        _IMPORT_ERROR = exc
        return None, None

def _ensure_chroma():
    # Fail fast on vector operations if Chroma could not be imported
    if _IMPORT_ERROR is not None:
        raise RuntimeError(f"chromadb is required. Original error: {_IMPORT_ERROR}")

def get_client():
    global _client
    _ensure_chroma()
    if _client is None:
        chromadb, Settings = _import_chromadb()
        path = config.CHROMA_PERSIST_DIR
        os.makedirs(path, exist_ok=True)
        # Persistent local Chroma client keeps precomputed vectors on disk across server reboots;
        # disabling telemetry avoids blocking network calls on startup
        _client = chromadb.PersistentClient(
            path=path,
            settings=Settings(anonymized_telemetry=False),
        )
    return _client

def get_collection():
    # Return the single shared knowledge collection
    client = get_client()
    return client.get_or_create_collection(name="knowledge")

def _metadata(chunk: Dict) -> Dict:
    # Store only the metadata needed for filtering and display.
    return {
        "source": chunk.get("source", ""),
        "type": chunk.get("type", ""),
        "name": chunk.get("name", ""),
        "category": chunk.get("category", ""),
    }

def _prepare_chunk_payload(chunks: List[Dict]):
    ids = [chunk["id"] for chunk in chunks]
    documents = [chunk["text"] for chunk in chunks]
    return ids, documents, embed_texts(documents), [_metadata(chunk) for chunk in chunks]

def add_chunks(chunks: List[Dict]) -> None:
    # Add new chunks to Chroma with embeddings and metadata.
    if not chunks:
        return
    _ensure_chroma()
    ids, docs, embs, metas = _prepare_chunk_payload(chunks)
    get_collection().add(ids=ids, documents=docs, embeddings=embs, metadatas=metas)

def upsert_chunks(chunks: List[Dict]) -> None:
    # Add or update chunk embeddings in Chroma with metadata.
    if not chunks:
        return
    _ensure_chroma()
    ids, docs, embs, metas = _prepare_chunk_payload(chunks)
    get_collection().upsert(ids=ids, documents=docs, embeddings=embs, metadatas=metas)

def reset_collection() -> None:
    """Safely reset/recreate the knowledge collection to prevent dimensional mismatches
    when switching embedding models (e.g. migrating to Gemini embeddings).
    """
    _ensure_chroma()
    client = get_client()
    try:
        client.delete_collection("knowledge")
    except Exception:
        pass
    client.get_or_create_collection(name="knowledge")

def delete_chunks(ids: List[str]) -> None:
    # Remove vectors by chunk ID when Markdown sources change or are deleted.
    if not ids:
        return
    _ensure_chroma()
    collection = get_collection()
    collection.delete(ids=ids)

def retrieve(query: str, top_k: int = 5) -> List[Dict]:
    # Semantic search: embed user query with the same model to project it into the vector space
    if not query.strip():
        return []
    _ensure_chroma()
    collection = get_collection()
    try:
        query_embedding = embed_query(query)
        # Include distances to allow calling layers to evaluate semantic confidence and filter noise
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )
    except Exception:
        # Resilient fallback: When embedding API is unavailable (e.g., HTTP 429 quota exhaustion or offline),
        # perform lexical matching directly against knowledge documents in Chroma or on disk
        results = None

    if not results or not results.get("documents") or not results.get("documents", [[]])[0]:
        # Fallback keyword matching against all knowledge chunks
        try:
            raw = collection.get(include=["documents", "metadatas"])
            docs = raw.get("documents") or []
            metas = raw.get("metadatas") or []
            ids_list = raw.get("ids") or []
            
            # If Chroma collection is empty, load directly from knowledge directory markdown files
            if not docs:
                from pathlib import Path
                from app.services.chunker import chunk_markdown
                k_dir = Path(__file__).resolve().parent.parent.parent / "knowledge"
                for md_file in k_dir.glob("*.md"):
                    try:
                        for chunk in chunk_markdown(md_file.read_text(encoding="utf-8"), md_file.name):
                            ids_list.append(chunk["id"])
                            docs.append(chunk["text"])
                            metas.append({
                                "source": chunk.get("source", ""),
                                "type": chunk.get("type", ""),
                                "name": chunk.get("name", ""),
                                "category": chunk.get("category", ""),
                            })
                    except Exception:
                        pass

            query_tokens = [w.lower() for w in re.findall(r"\w+", query) if len(w) > 2]
            scored_candidates = []
            for idx, text in enumerate(docs):
                t_lower = text.lower()
                meta = metas[idx] if idx < len(metas) else {}
                meta_str = " ".join(str(v).lower() for v in meta.values())
                match_count = sum(1 for token in query_tokens if token in t_lower or token in meta_str)
                if match_count > 0:
                    scored_candidates.append((match_count, idx))

            scored_candidates.sort(key=lambda x: x[0], reverse=True)
            hits = []
            for _, idx in scored_candidates[:top_k]:
                hits.append({
                    "id": ids_list[idx] if idx < len(ids_list) else None,
                    "content": docs[idx],
                    "metadata": metas[idx] if idx < len(metas) else {},
                    "score": 0.5,  # Synthesized confident score for lexical hit
                })
            return hits
        except Exception:
            return []
    hits: List[Dict] = []
    ids = results.get("ids", [[]])[0]
    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]
    for idx, doc in enumerate(documents):
        hits.append(
            {
                "id": ids[idx] if idx < len(ids) else None,
                "content": doc,
                "metadata": metadatas[idx] if idx < len(metadatas) else {},
                # Distance score (lower distance = closer semantic match in ChromaDB cosine space)
                "score": distances[idx] if idx < len(distances) else None,
            }
        )
    return hits