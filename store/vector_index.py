import numpy as np
from pathlib import Path

from config import FAISS_DIR


class VectorIndex:
    def __init__(self, dimension: int = 512, index_path: str | None = None):
        import faiss
        self.dimension = dimension
        self.index = faiss.IndexFlatIP(dimension)
        self.id_map: list[int] = []

        if index_path:
            self.load(index_path)
        else:
            default_path = FAISS_DIR / "index.faiss"
            if default_path.exists():
                self.load(str(default_path))

    def add(self, image_id: int, embedding: np.ndarray):
        if embedding.shape[0] != self.dimension:
            embedding = embedding[:self.dimension] if embedding.shape[0] > self.dimension else \
                np.pad(embedding, (0, self.dimension - embedding.shape[0]))
        self.index.add(embedding.reshape(1, -1))
        self.id_map.append(image_id)

    def search(self, query_embedding: np.ndarray, top_k: int = 10) -> list[tuple[int, float]]:
        if query_embedding.shape[0] != self.dimension:
            query_embedding = query_embedding[:self.dimension] if query_embedding.shape[0] > self.dimension else \
                np.pad(query_embedding, (0, self.dimension - query_embedding.shape[0]))

        scores, indices = self.index.search(query_embedding.reshape(1, -1), min(top_k, len(self.id_map)))
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx >= 0 and idx < len(self.id_map):
                results.append((self.id_map[idx], float(score)))
        return results

    def search_by_text(self, query: str, top_k: int = 10) -> list[tuple[int, float]]:
        import open_clip
        import torch

        model, _, preprocess = open_clip.create_model_and_transforms("ViT-B-32", pretrained="openai")
        tokenizer = open_clip.get_tokenizer("ViT-B-32")
        model.eval()

        text_tokens = tokenizer([query])
        with torch.no_grad():
            text_features = model.encode_text(text_tokens)
            text_features = text_features / text_features.norm(dim=-1, keepdim=True)
        query_embedding = text_features.squeeze().numpy().astype("float32")

        return self.search(query_embedding, top_k)

    def save(self, path: str | None = None):
        import faiss
        path = path or str(FAISS_DIR / "index.faiss")
        FAISS_DIR.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self.index, path)
        id_map_path = Path(path).with_suffix(".ids")
        id_map_path.write_text(",".join(str(i) for i in self.id_map))

    def load(self, path: str):
        import faiss
        self.index = faiss.read_index(path)
        id_map_path = Path(path).with_suffix(".ids")
        if id_map_path.exists():
            self.id_map = [int(x) for x in id_map_path.read_text().split(",") if x]
