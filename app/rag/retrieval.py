"""
Retrieval utilities and Reciprocal Rank Fusion (RRF) algorithms.
"""
import numpy as np
from typing import List, Dict, Any, Optional


def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Compute cosine similarity between two vectors."""
    a = np.array(v1, dtype=np.float32)
    b = np.array(v2, dtype=np.float32)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def reciprocal_rank_fusion(
    ranked_lists: List[List[Dict[str, Any]]],
    key_field: str = "id",
    k: int = 60,
) -> List[Dict[str, Any]]:
    """
    Combine multiple ranked result lists using Reciprocal Rank Fusion (RRF).
    score(d) = sum(1 / (k + rank_i(d)))
    """
    scores: Dict[Any, float] = {}
    items: Dict[Any, Dict[str, Any]] = {}

    for ranked_list in ranked_lists:
        for rank, item in enumerate(ranked_list):
            item_id = item.get(key_field)
            if item_id is None:
                continue

            if item_id not in scores:
                scores[item_id] = 0.0
                items[item_id] = item

            scores[item_id] += 1.0 / (k + rank + 1)

    # Sort items by fused RRF score
    sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
    fused_results = []
    for item_id in sorted_ids:
        item = dict(items[item_id])
        item["rrf_score"] = round(scores[item_id], 6)
        fused_results.append(item)

    return fused_results
