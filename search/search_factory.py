"""Search backend factory.

Selects between SearXNG and DuckDuckGo based on config or CLI flag.
In 'auto' mode, tries SearXNG first and falls back to DuckDuckGo.
"""
from __future__ import annotations

import sys


class SearchBackendError(Exception):
    pass


def get_searcher(backend: str | None = None):
    """Return the search_images function for the chosen backend.

    Args:
        backend: "auto" | "searxng" | "duckduckgo". None reads from config.
    """
    if backend is None:
        from config import DEFAULT_SEARCH_BACKEND
        backend = DEFAULT_SEARCH_BACKEND

    if backend == "duckduckgo":
        from search.duckduckgo_searcher import search_images
        return search_images

    if backend == "searxng":
        from search.searxng_searcher import search_images, SearchBackendError as SearXNGError
        def _searxng_wrapper(**kwargs):
            try:
                return search_images(**kwargs)
            except Exception as e:
                raise SearchBackendError(f"SearXNG error: {e}") from e
        return _searxng_wrapper

    # "auto" — try SearXNG, fall back to DuckDuckGo
    from config import SEARXNG_BASE_URL

    if SEARXNG_BASE_URL:
        from search.searxng_searcher import search_images as searxng_search
        from search.duckduckgo_searcher import search_images as ddg_search

        def _auto_search(**kwargs):
            try:
                # Health-check: try one result
                kwargs_copy = {**kwargs, "max_results": min(kwargs.get("max_results", 30), 1)}
                result = searxng_search(**kwargs_copy)
                if result:
                    # Re-run with full count if health check passed
                    return searxng_search(**kwargs) if kwargs["max_results"] > 1 else result
            except Exception as e:
                print(f"[search] SearXNG unavailable ({e}), falling back to DuckDuckGo", file=sys.stderr)
            return ddg_search(**kwargs)
        return _auto_search

    # No SearXNG configured, use DuckDuckGo directly
    from search.duckduckgo_searcher import search_images
    return search_images
