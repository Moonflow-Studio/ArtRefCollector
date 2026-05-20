from pathlib import Path

import numpy as np
from tqdm import tqdm

from store.embedding_utils import encode_image


def find_duplicates_clip(
    image_records: list[dict],
    similarity_threshold: float = 0.95,
) -> list[list[str]]:
    embeddings: list[tuple[str, np.ndarray]] = []
    for rec in image_records:
        path = rec.get("local_path", "")
        if not path or not Path(path).exists():
            continue
        emb = encode_image(path)
        if emb is not None:
            identifier = rec.get("filename", path)
            embeddings.append((identifier, emb))
            # Persist embedding back into record for downstream vector index
            rec["clip_embedding"] = emb.tolist()

    if len(embeddings) < 2:
        return []

    ids = [e[0] for e in embeddings]
    matrix = np.stack([e[1] for e in embeddings])
    similarity = matrix @ matrix.T

    groups = []
    used = set()
    for i in range(len(ids)):
        if i in used:
            continue
        group = [ids[i]]
        for j in range(i + 1, len(ids)):
            if j in used:
                continue
            if similarity[i][j] >= similarity_threshold:
                group.append(ids[j])
                used.add(j)
        if len(group) > 1:
            groups.append(group)
            used.add(i)

    return groups
