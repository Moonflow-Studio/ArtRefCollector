from duckduckgo_search import DDGS


def search_images(
    keywords: str,
    max_results: int = 30,
    region: str = "wt-wt",
    safesearch: str = "moderate",
    size: str | None = None,
    type_image: str | None = None,
    layout: str | None = None,
) -> list[dict]:
    with DDGS() as ddgs:
        kwargs = {
            "keywords": keywords,
            "region": region,
            "safesearch": safesearch,
            "max_results": max_results,
        }
        if size:
            kwargs["size"] = size
        if type_image:
            kwargs["type_image"] = type_image
        if layout:
            kwargs["layout"] = layout

        results = list(ddgs.images(**kwargs))

    return [
        {
            "title": r.get("title", ""),
            "image_url": r.get("image", ""),
            "thumbnail": r.get("thumbnail", ""),
            "source_url": r.get("url", ""),
            "width": r.get("width", 0),
            "height": r.get("height", 0),
            "source": r.get("source", ""),
        }
        for r in results
    ]
