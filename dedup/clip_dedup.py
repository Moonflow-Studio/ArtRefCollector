from pathlib import Path

import numpy as np
import torch
from PIL import Image
from tqdm import tqdm


_model = None
_preprocess = None


def _load_model():
    global _model, _preprocess
    if _model is not None:
        return
    import open_clip
    _model, _, _preprocess = open_clip.create_model_and_transforms("ViT-B-32", pretrained="openai")
    _model.eval()


def compute_clip_embedding(image_path: str) -> np.ndarray | None:
    _load_model()
    try:
        img = Image.open(image_path).convert("RGB")
        image_tensor = _preprocess(img).unsqueeze(0)
        with torch.no_grad():
            features = _model.encode_image(image_tensor)
            features = features / features.norm(dim=-1, keepdim=True)
        return features.squeeze().numpy().astype("float32")
    except Exception:
        return None


def find_duplicates_clip(
    image_records: list[dict],
    similarity_threshold: float = 0.95,
) -> list[list[str]]:
    embeddings: list[tuple[str, np.ndarray]] = []
    for rec in image_records:
        path = rec.get("local_path", "")
        if not path or not Path(path).exists():
            continue
        emb = compute_clip_embedding(path)
        if emb is not None:
            identifier = rec.get("filename", path)
            embeddings.append((identifier, emb))

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
