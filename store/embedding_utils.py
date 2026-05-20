"""Shared CLIP model loading and encoding utilities.

Used by vector_index.py (text search), clip_dedup.py (image embedding),
and cmd_store (embedding gap fix).
"""
import numpy as np
import torch
from PIL import Image

_model = None
_preprocess = None
_tokenizer = None


def get_clip_model():
    """Lazy-load CLIP ViT-B-32 model. Returns (model, preprocess, tokenizer)."""
    global _model, _preprocess, _tokenizer
    if _model is None:
        import open_clip
        _model, _, _preprocess = open_clip.create_model_and_transforms("ViT-B-32", pretrained="openai")
        _tokenizer = open_clip.get_tokenizer("ViT-B-32")
        _model.eval()
    return _model, _preprocess, _tokenizer


def encode_text(query: str) -> np.ndarray:
    """Encode text query to 512-dim L2-normalized float32 vector."""
    model, _, tokenizer = get_clip_model()
    text_tokens = tokenizer([query])
    with torch.no_grad():
        features = model.encode_text(text_tokens)
        features = features / features.norm(dim=-1, keepdim=True)
    return features.squeeze().numpy().astype("float32")


def encode_image(image_path: str) -> np.ndarray | None:
    """Encode image to 512-dim L2-normalized float32 vector. Returns None on error."""
    model, preprocess, _ = get_clip_model()
    try:
        img = Image.open(image_path).convert("RGB")
        image_tensor = preprocess(img).unsqueeze(0)
        with torch.no_grad():
            features = model.encode_image(image_tensor)
            features = features / features.norm(dim=-1, keepdim=True)
        return features.squeeze().numpy().astype("float32")
    except Exception:
        return None
