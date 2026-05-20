import asyncio
import hashlib
from pathlib import Path

import httpx
from PIL import Image
from io import BytesIO
from tqdm import tqdm

from config import DEFAULT_MIN_FILE_SIZE, DEFAULT_THUMBNAIL_SIZE, THUMBNAILS_DIR


def _file_extension(url: str) -> str:
    path = url.split("?")[0].split("#")[0]
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"):
        if path.lower().endswith(ext):
            return ext
    return ".jpg"


def _generate_filename(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:16] + _file_extension(url)


async def download_one(client: httpx.AsyncClient, item: dict, output_dir: str, semaphore: asyncio.Semaphore, retries: int = 2) -> dict:
    url = item.get("image_url", "")
    if not url:
        return {**item, "status": "skipped", "error": "no url"}

    filename = _generate_filename(url)
    local_path = str(Path(output_dir) / filename)

    async with semaphore:
        for attempt in range(retries + 1):
            try:
                resp = await client.get(url, follow_redirects=True, timeout=15)
                resp.raise_for_status()

                if len(resp.content) < DEFAULT_MIN_FILE_SIZE:
                    return {**item, "status": "skipped", "error": "too_small"}

                Path(local_path).write_bytes(resp.content)

                # Generate thumbnail
                try:
                    img = Image.open(BytesIO(resp.content))
                    thumb_name = "thumb_" + filename
                    thumb_path = str(THUMBNAILS_DIR / thumb_name)
                    img.thumbnail(DEFAULT_THUMBNAIL_SIZE)
                    img.save(thumb_path)
                    thumbnail_path = thumb_path
                except Exception:
                    thumbnail_path = ""

                return {
                    **item,
                    "filename": filename,
                    "local_path": local_path,
                    "thumbnail_path": thumbnail_path,
                    "file_size": len(resp.content),
                    "status": "success",
                }
            except Exception as e:
                if attempt == retries:
                    return {**item, "status": "failed", "error": str(e)}
                await asyncio.sleep(0.5 * (attempt + 1))

    return {**item, "status": "failed"}


async def download_images(
    url_list: list[dict],
    output_dir: str,
    max_concurrent: int = 5,
) -> list[dict]:
    THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(max_concurrent)
    results = []

    async with httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0"}) as client:
        tasks = [download_one(client, item, output_dir, semaphore) for item in url_list]
        for coro in tqdm(asyncio.as_completed(tasks), total=len(tasks), desc="Downloading"):
            results.append(await coro)

    success = sum(1 for r in results if r.get("status") == "success")
    print(f"Downloaded {success}/{len(results)} images", file=__import__("sys").stderr)
    return results
