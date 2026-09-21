from __future__ import annotations

from math import sqrt
from typing import Any, Dict, Iterable, List, Optional


def rewrite_query(query: str, synonyms: Optional[Dict[str, List[str]]] = None) -> str:
    """Expand query terms with simple synonyms or paraphrase alternatives."""
    rewritten = query.strip()
    if not rewritten:
        return rewritten

    synonyms = synonyms or {}
    parts = rewritten.lower().split()
    expanded: List[str] = []

    for part in parts:
        alternatives = synonyms.get(part.lower(), [])
        if alternatives:
            expanded.append(part)
            expanded.extend(alternatives)
        else:
            expanded.append(part)

    return ' '.join(expanded)


def cosine_similarity(vec_a: Iterable[float], vec_b: Iterable[float]) -> float:
    a = list(vec_a)
    b = list(vec_b)
    if len(a) != len(b):
        raise ValueError('Embedding vectors must have the same length')
    if not a:
        return 0.0

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sqrt(sum(x * x for x in a))
    norm_b = sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def apply_filters(chunks: Iterable[Dict[str, Any]], filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    if not filters:
        return list(chunks)

    filtered: List[Dict[str, Any]] = []
    for chunk in chunks:
        match = True
        for key, value in filters.items():
            if chunk.get(key) != value:
                match = False
                break
        if match:
            filtered.append(chunk)
    return filtered


def rerank_results(chunks: Iterable[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
    scored = []
    query_lower = query.lower()
    for chunk in chunks:
        text = str(chunk.get('text', ''))
        score = text.lower().count(query_lower)
        if score > 0:
            score += 1
        scored.append({**chunk, '_rerank_score': score})
    scored.sort(key=lambda item: item['_rerank_score'], reverse=True)
    return [{k: v for k, v in item.items() if k != '_rerank_score'} for item in scored]


def retrieve_top_k(
    chunks: Iterable[Dict[str, Any]],
    query: str,
    top_k: int = 5,
    filters: Optional[Dict[str, Any]] = None,
    query_rewrite: bool = False,
    rerank: bool = False,
    synonyms: Optional[Dict[str, List[str]]] = None,
    embedding_key: str = 'embedding',
) -> List[Dict[str, Any]]:
    """Return top-k chunk matches with optional filtering, query rewrites, and reranking."""
    query_text = rewrite_query(query, synonyms) if query_rewrite else query
    filtered = apply_filters(chunks, filters)

    scored: List[Dict[str, Any]] = []
    for chunk in filtered:
        embedding = chunk.get(embedding_key)
        if embedding is None:
            similarity = 0.0
        else:
            similarity = cosine_similarity(embedding, [1.0] * len(embedding))
        scored.append({**chunk, '_score': similarity})

    scored.sort(key=lambda item: item['_score'], reverse=True)
    results = scored[:top_k]

    if rerank:
        results = rerank_results(results, query_text)

    return results
