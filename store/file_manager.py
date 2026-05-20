import shutil
from pathlib import Path

from config import IMAGES_DIR, THUMBNAILS_DIR, DEFAULT_THUMBNAIL_SIZE
from dedup.phash_dedup import compute_phash


def organize_files(downloads: list[dict], topic: str) -> list[dict]:
    topic_dir = IMAGES_DIR / topic
    topic_dir.mkdir(parents=True, exist_ok=True)

    organized = []
    for item in downloads:
        if item.get("status") != "success":
            continue

        src_path = Path(item.get("local_path", ""))
        if not src_path.exists():
            continue

        dest_path = topic_dir / src_path.name
        if src_path != dest_path:
            shutil.move(str(src_path), str(dest_path))

        phash = compute_phash(str(dest_path)) or ""

        organized.append({
            **item,
            "local_path": str(dest_path),
            "phash": phash,
        })

    return organized
