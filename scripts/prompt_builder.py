from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional


def build_context_prompt(
    query: str,
    chunks: Iterable[Dict[str, Any]],
    *,
    system_prompt: str = "You are a careful assistant. Use the provided evidence to answer accurately and cite the source when possible.",
    max_chunks: Optional[int] = None,
    include_metadata: bool = True,
) -> str:
    """Construct an LLM prompt that injects retrieved chunks and source metadata into context."""
    chunk_list = list(chunks)
    if max_chunks is not None:
        chunk_list = chunk_list[:max_chunks]

    context_lines: List[str] = []
    for index, chunk in enumerate(chunk_list, start=1):
        text = str(chunk.get('text') or chunk.get('content') or '').strip()
        if not text:
            continue

        source = chunk.get('source') or 'unknown'
        chunk_id = chunk.get('id', index)
        metadata = chunk.get('metadata') or {}

        if include_metadata:
            meta_text = ', '.join(f'{key}={value}' for key, value in metadata.items()) if metadata else 'no additional metadata'
            context_lines.append(
                f"[Chunk {index}] id={chunk_id} source={source} metadata={meta_text}\n{text}\n"
            )
        else:
            context_lines.append(f"[Chunk {index}] source={source}\n{text}\n")

    context_block = '\n'.join(context_lines) if context_lines else 'No relevant retrieved chunks were found.'

    prompt = f"""{system_prompt}

User question:
{query}

Retrieved evidence:
{context_block}

Instructions:
1. Answer the user's question using the retrieved evidence.
2. Prefer the most relevant chunks and ignore unsupported assumptions.
3. If evidence is insufficient, say so clearly.
4. Include source names or IDs when referencing evidence.
"""
    return prompt


if __name__ == '__main__':
    demo_chunks = [
        {
            'id': 1,
            'source': 'support_policy.md',
            'text': 'Refunds are allowed within 30 days for eligible purchases.',
            'metadata': {'section': 'refunds', 'doc_type': 'policy'},
        },
        {
            'id': 2,
            'source': 'faq.md',
            'text': 'Customers can request reimbursement after approval from the finance team.',
            'metadata': {'section': 'billing'},
        },
    ]
    print(build_context_prompt('Can I get a refund?', demo_chunks))
