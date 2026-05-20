"""Download backend factory.

Selects between gallery-dl and httpx based on config or CLI flag.
In 'auto' mode, uses gallery-dl (with httpx fallback) and optionally
retries failures with img2dataset.
"""
from __future__ import annotations

import sys


def get_downloader(backend: str | None = None):
    """Return the download_images function for the chosen backend.

    Args:
        backend: "auto" | "gallery-dl" | "httpx". None reads from config.
    """
    if backend is None:
        from config import DEFAULT_DOWNLOAD_BACKEND
        backend = DEFAULT_DOWNLOAD_BACKEND

    if backend == "httpx":
        from download.downloader import download_images
        return download_images

    # "gallery-dl" or "auto" — use gallery-dl with httpx fallback
    from download.gallery_dl_downloader import download_images as gdl_download

    if backend == "gallery-dl":
        return gdl_download

    # "auto" — gallery-dl + optional img2dataset retry
    from config import IMG2DATASET_FALLBACK

    if not IMG2DATASET_FALLBACK:
        return gdl_download

    from download.img2dataset_fallback import retry_failed

    async def _auto_download(url_list, output_dir, max_concurrent=5):
        results = await gdl_download(url_list, output_dir, max_concurrent)
        failed = [r for r in results if r.get("status") == "failed"]
        if failed:
            print(f"[download] Retrying {len(failed)} failed items with img2dataset...", file=sys.stderr)
            retried = retry_failed(failed, output_dir)
            # Merge retried results back
            retried_map = {id(r): r for r in retried}
            merged = [retried_map.get(id(r), r) for r in results]
            success = sum(1 for r in merged if r.get("status") == "success")
            print(f"[download] After retry: {success}/{len(merged)} successful", file=sys.stderr)
            return merged
        return results

    return _auto_download
