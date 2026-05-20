"""gallery-dl based downloader.

Primary download backend: tries gallery-dl for each URL, falls back to
httpx for direct image URLs that gallery-dl cannot handle.
"""
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from tqdm import tqdm

from download.downloader import download_one
from config import DEFAULT_MIN_FILE_SIZE, THUMBNAILS_DIR

import httpx


def _generate_filename(url: str) -> str:
    path = url.split("?")[0].split("#")[0]
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"):
        if path.lower().endswith(ext):
            return hashlib.md5(url.encode()).hexdigest()[:16] + ext
    return hashlib.md5(url.encode()).hexdigest()[:16] + ".jpg"


def _try_gallery_dl(url: str, output_dir: str) -> str | None:
    """Try downloading with gallery-dl. Returns local path or None."""
    try:
        import gallery_dl
        import gallery_dl.config as gdl_config

        # Configure gallery-dl output
        gdl_config.set(("base-directory",), output_dir)
        gdl_config.set(("output", "mode"), "direct")

        job = gallery_dl.job.DownloadJob(url)
        # Override destination
        job.pathfmt = None  # let gallery-dl handle it

        with Path(output_dir) as od:
            od.mkdir(parents=True, exist_ok=True)

        # Run download — returns number of downloads
        cnt = job.run()
        if cnt and cnt > 0:
            # gallery-dl wrote files; find the most recent one in output_dir
            import os
            files = sorted(Path(output_dir).iterdir(), key=os.path.getmtime, reverse=True)
            for f in files:
                if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"):
                    if f.stat().st_size >= DEFAULT_MIN_FILE_SIZE:
                        return str(f)
        return None
    except Exception:
        return None


async def _download_one_with_fallback(
    client: httpx.AsyncClient,
    item: dict,
    output_dir: str,
    semaphore: asyncio.Semaphore,
    loop: asyncio.AbstractEventLoop,
) -> dict:
    """Try gallery-dl first, then httpx fallback."""
    url = item.get("image_url", "")
    if not url:
        return {**item, "status": "skipped", "error": "no url"}

    filename = _generate_filename(url)
    local_path = str(Path(output_dir) / filename)

    # Try gallery-dl (in thread pool to avoid blocking)
    gdl_path = await loop.run_in_executor(None, _try_gallery_dl, url, output_dir)
    if gdl_path and Path(gdl_path).exists():
        from PIL import Image
        from io import BytesIO
        from config import DEFAULT_THUMBNAIL_SIZE

        file_bytes = Path(gdl_path).read_bytes()
        actual_filename = Path(gdl_path).name

        # If gallery-dl gave a different filename, use it
        if actual_filename != filename:
            local_path = gdl_path

        # Generate thumbnail
        thumbnail_path = ""
        try:
            img = Image.open(BytesIO(file_bytes))
            thumb_name = "thumb_" + actual_filename
            thumb_path = str(THUMBNAILS_DIR / thumb_name)
            img.thumbnail(DEFAULT_THUMBNAIL_SIZE)
            img.save(thumb_path)
            thumbnail_path = thumb_path
        except Exception:
            pass

        return {
            **item,
            "filename": actual_filename,
            "local_path": local_path,
            "thumbnail_path": thumbnail_path,
            "file_size": len(file_bytes),
            "status": "success",
        }

    # Fallback to httpx
    return await download_one(client, item, output_dir, semaphore)


async def download_images(
    url_list: list[dict],
    output_dir: str,
    max_concurrent: int = 5,
) -> list[dict]:
    """Download images using gallery-dl with httpx fallback."""
    THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(max_concurrent)
    loop = asyncio.get_event_loop()
    results = []

    async with httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0"}) as client:
        tasks = [
            _download_one_with_fallback(client, item, output_dir, semaphore, loop)
            for item in url_list
        ]
        for coro in tqdm(asyncio.as_completed(tasks), total=len(tasks), desc="Downloading"):
            results.append(await coro)

    success = sum(1 for r in results if r.get("status") == "success")
    print(f"Downloaded {success}/{len(results)} images", file=__import__("sys").stderr)
    return results
