"""img2dataset fallback downloader.

Retries failed downloads using img2dataset for batch processing.
"""
from __future__ import annotations

import tempfile
import shutil
from pathlib import Path

from config import DEFAULT_MIN_FILE_SIZE


def retry_failed(
    failed_items: list[dict],
    output_dir: str,
    thread_count: int = 8,
) -> list[dict]:
    """Retry failed downloads using img2dataset.

    Args:
        failed_items: Items with status == "failed" from primary downloader.
        output_dir: Target directory for downloaded files.

    Returns:
        Updated items with status changed to "success" where img2dataset succeeded.
    """
    if not failed_items:
        return failed_items

    urls = []
    for item in failed_items:
        url = item.get("image_url", "")
        if url:
            urls.append(url)

    if not urls:
        return failed_items

    # Write URL list to temp file
    tmp_dir = tempfile.mkdtemp(prefix="img2dataset_")
    url_file = Path(tmp_dir) / "urls.txt"
    url_file.write_text("\n".join(urls))

    i2d_output = Path(tmp_dir) / "output"
    i2d_output.mkdir(parents=True, exist_ok=True)

    try:
        from img2dataset import download as i2d_download

        i2d_download(
            url_list=str(url_file),
            image_size=512,
            output_folder=str(i2d_output),
            thread_count=thread_count,
            resize_mode="no",
            output_format="files",
        )
    except Exception as e:
        print(f"[img2dataset] Fallback failed: {e}", file=__import__("sys").stderr)
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return failed_items

    # Map downloaded files back to items
    downloaded = {}
    for f in (i2d_output / "00000").iterdir():
        if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
            downloaded[f.stem] = f

    results = []
    for item in failed_items:
        url = item.get("image_url", "")
        url_hash = __import__("hashlib").md5(url.encode()).hexdigest()[:16]

        matched_file = None
        for stem, f in downloaded.items():
            if url_hash in stem or stem in url:
                matched_file = f
                break

        if matched_file and matched_file.stat().st_size >= DEFAULT_MIN_FILE_SIZE:
            dest = Path(output_dir) / matched_file.name
            shutil.move(str(matched_file), str(dest))
            results.append({
                **item,
                "filename": dest.name,
                "local_path": str(dest),
                "file_size": dest.stat().st_size,
                "status": "success",
                "error": "",
            })
        else:
            results.append(item)

    shutil.rmtree(tmp_dir, ignore_errors=True)
    return results
