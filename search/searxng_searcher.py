"""SearXNG image search backend.

Calls a SearXNG instance's JSON API and normalizes results to the
standard search result contract.
"""
from __future__ import annotations

import httpx
from urllib.parse import urlparse


def search_images(
    keywords: str,
    max_results: int = 30,
    region: str = "wt-wt",
    safesearch: str = "moderate",
    size: str | None = None,
    type_image: str | None = None,
    layout: str | None = None,
    base_url: str = "",
) -> list[dict]:
    """Search images via SearXNG JSON API.

    Returns list of dicts with keys:
      {title, image_url, thumbnail, source_url, width, height, source}
    """
    if not base_url:
        from config import SEARXNG_BASE_URL
        base_url = SEARXNG_BASE_URL
    if not base_url:
        raise SearchBackendError("SearXNG base URL not configured")

    params = {
        "q": keywords,
        "format": "json",
        "categories": "images",
        "pagenation": "0",
    }
    if safesearch == "strict":
        params["safesearch"] = "2"
    elif safesearch == "moderate":
        params["safesearch"] = "1"

    resp = httpx.get(
        f"{base_url.rstrip('/')}/search",
        params=params,
        headers={"User-Agent": "ArtRefCollector/0.2"},
        timeout=15.0,
    )
    resp.raise_for_status()
    data = resp.json()

    results = []
    for r in data.get("results", [])[:max_results]:
        source = ""
        parsed = r.get("parsed_url")
        if isinstance(parsed, dict):
            source = parsed.get("netloc", "")
        elif not source:
            try:
                source = urlparse(r.get("url", "")).netloc
            except Exception:
                pass

        results.append({
            "title": r.get("title", ""),
            "image_url": r.get("img_src", r.get("url", "")),
            "thumbnail": r.get("thumbnail_src", ""),
            "source_url": r.get("url", ""),
            "width": r.get("image_resolution", [0, 0])[0] if isinstance(r.get("image_resolution"), list) else 0,
            "height": r.get("image_resolution", [0, 0])[1] if isinstance(r.get("image_resolution"), list) else 0,
            "source": source,
        })

    return results


class SearchBackendError(Exception):
    pass
