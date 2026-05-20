from pathlib import Path

import imagehash
from PIL import Image


def compute_phash(image_path: str, hash_size: int = 16) -> str | None:
    try:
        img = Image.open(image_path)
        return str(imagehash.phash(img, hash_size=hash_size))
    except Exception:
        return None


def find_duplicates_phash(
    image_records: list[dict],
    hamming_threshold: int = 10,
) -> list[list[str]]:
    hashes: list[tuple[str, str]] = []
    for rec in image_records:
        path = rec.get("local_path", "")
        if not path or not Path(path).exists():
            continue
        h = compute_phash(path)
        if h:
            identifier = rec.get("filename", path)
            hashes.append((identifier, h))

    groups = []
    used = set()
    for i, (id_i, h_i) in enumerate(hashes):
        if i in used:
            continue
        group = [id_i]
        for j, (id_j, h_j) in enumerate(hashes):
            if j <= i or j in used:
                continue
            try:
                dist = imagehash.hex_to_hash(h_i) - imagehash.hex_to_hash(h_j)
                if dist <= hamming_threshold:
                    group.append(id_j)
                    used.add(j)
            except Exception:
                continue
        if len(group) > 1:
            groups.append(group)
            used.add(i)

    return groups
