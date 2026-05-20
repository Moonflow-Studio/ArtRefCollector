"""Scrape image URLs from reference pages and create sessions for art-ref-collector."""
import json
import re
import sys
import uuid
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from config import DATA_DIR, SESSIONS_DIR


def new_session() -> str:
    sid = uuid.uuid4().hex[:12]
    session_dir = SESSIONS_DIR / sid
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "search_results.json").write_text("[]")
    (session_dir / "downloads.json").write_text("[]")
    return sid


def save_session_data(sid: str, filename: str, data):
    path = SESSIONS_DIR / sid / filename
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
}

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff"}

SKIP_DOMAINS = {
    "google", "facebook", "twitter", "instagram", "youtube",
    "doubleclick", "googlesyndication", "analytics", "fonts",
    "icon", "logo", "badge", "button", "banner", "adservice",
}

SKIP_PATTERNS = [
    r"logo", r"icon", r"avatar", r"badge", r"button", r"banner",
    r"spinner", r"loading", r"placeholder", r"pixel", r"tracking",
    r"\d+x\d+",  # small sizes like 16x16, 32x32
]


def is_valid_image_url(url: str) -> bool:
    """Check if URL looks like a valid image URL."""
    if not url:
        return False
    parsed = urlparse(url)
    path_lower = parsed.path.lower()

    # Check extension
    has_img_ext = any(path_lower.endswith(ext) for ext in IMAGE_EXTENSIONS)
    if not has_img_ext and "image" not in url.lower() and "photo" not in url.lower() and "img" not in url.lower():
        return False

    # Skip small/irrelevant images
    for pattern in SKIP_PATTERNS:
        if re.search(pattern, url.lower()):
            return False

    # Skip certain domains
    for domain in SKIP_DOMAINS:
        if domain in parsed.netloc.lower():
            return False

    return True


def extract_images_from_page(page_url: str, max_images: int = 15) -> list[dict]:
    """Extract image URLs from a web page."""
    results = []
    try:
        resp = requests.get(page_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"  Failed to fetch {page_url}: {e}", file=sys.stderr)
        return results

    soup = BeautifulSoup(resp.text, "html.parser")
    base_url = resp.url

    # Extract from og:image meta tags (high quality)
    for meta in soup.find_all("meta", property="og:image"):
        url = meta.get("content", "")
        if url and is_valid_image_url(url):
            url = urljoin(base_url, url)
            results.append({"url": url, "source": page_url})

    # Extract from img tags
    seen = set()
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-lazy-src") or ""
        if not src:
            continue
        src = urljoin(base_url, src)
        if src in seen:
            continue
        seen.add(src)

        # Filter by size hints
        width = img.get("width", "")
        height = img.get("height", "")
        if width and height:
            try:
                if int(width) < 200 or int(height) < 150:
                    continue
            except ValueError:
                pass

        if is_valid_image_url(src):
            results.append({"url": src, "source": page_url})

    # Extract from srcset
    for img in soup.find_all("img", srcset=True):
        srcset = img.get("srcset", "")
        for entry in srcset.split(","):
            parts = entry.strip().split()
            if parts:
                url = urljoin(base_url, parts[0])
                if is_valid_image_url(url) and url not in seen:
                    seen.add(url)
                    results.append({"url": url, "source": page_url})

    return results[:max_images]


def fetch_direct_image_urls(image_page_urls: list[str], topic: str) -> list[dict]:
    """Fetch images from multiple pages and create session data."""
    all_images = []
    seen_urls = set()

    for i, page_url in enumerate(image_page_urls):
        print(f"  [{i+1}/{len(image_page_urls)}] Scraping: {page_url[:80]}...")
        images = extract_images_from_page(page_url, max_images=8)
        for img in images:
            if img["url"] not in seen_urls:
                seen_urls.add(img["url"])
                all_images.append({
                    "title": f"{topic} reference",
                    "image_url": img["url"],
                    "thumbnail": img["url"],
                    "source_url": img["source"],
                    "width": 0,
                    "height": 0,
                    "source": urlparse(img["source"]).netloc,
                })
        print(f"    Found {len(images)} images")

    return all_images


# Reference page URLs organized by scene
SCENE_PAGES = {
    "S3_屏蔽室": {
        "description": "室内·抽象·极简光 — 气密门内外两个世界",
        "pages": [
            "https://www.alamy.com/stock-photo-brutalist-architecture-pedestrian-hallway-in-the-barbican-complex-105402331.html",
            "https://www.architecturaleye.co.uk/portfolios/photographic-portfolio-barbican-centre/",
            "https://www.ekebergparken.com/en/kunst/skyspace-ganzfeld",
            "https://www.flickr.com/photos/andrewpaulcarr/237025822/",
            "https://www.flickr.com/photos/faiecca/7485724988",
            "https://www.flickr.com/photos/jurvetson/6940136304/",
            "https://www.flickr.com/photos/nasahubble/27924268092",
            "https://www.flickr.com/photos/36692623@N06/8097117724",
            "https://www.scouty.com/location/brutalist-concrete-bunker-66c35164513b100015e0831f",
            "https://www.mooponto.com/architecture/church-of-the-light-tadao-ando-architect-associates/",
            "https://artsandculture.google.com/asset/the-church-of-light-1989-tadao-ando-osaka-japan-tadao-ando/vAFA7VAEw71p6A?hl=en",
        ],
    },
    "S1_焰砂海矿营": {
        "description": "室外·晴日·远中近 — 苍茫辽阔的荒漠矿营",
        "pages": [
            "https://www.martyquinn.com/blog/monument-valley-photography-guide",
            "https://duncan.co/monument-valley-at-dusk/",
            "https://duncan.co/monument-valley-sunset-panorama/",
            "https://500px.com/photo/84915105/shadows-monument-valley-by-frank-delargy",
            "https://imaggeo.egu.eu/view/4985/",
            "https://www.smithsonianmag.com/travel/unearthing-coober-pedy-australias-hidden-city-180958162/",
            "https://www.cooberpedy.com/about-coober-pedy-2/",
            "https://savingplaces.org/stories/preserving-decay-exploring-the-ghost-town-of-bodie-california",
            "https://californiacrossings.com/bodie-ghost-town-state-park/",
            "https://planetwhitley.com/rhyolite-a-practical-visitor-guide-to-nevadas-most-photogenic-ghost-town/",
            "https://www.martinkingphotography.com/blog/rhyolite-gold-rush-ghost-town",
            "https://nocamerabag.com/blog/rhyolite-ghost-town-nevada",
            "https://www.artchive.com/artwork/sunlight-on-brownstones-edward-hopper-1956/",
            "https://www.artchive.com/artwork/cape-cod-afternoon-edward-hopper-1936/",
            "https://blog.mingthein.com/2016/09/10/photoessay-australian-ochre/",
            "https://mitchgreenphotos.com/articles/the-guide-to-photographing-uluru",
        ],
    },
    "S7_冠脊林活矿林": {
        "description": "室外·异星生态·远中近 — 矿与生命共生的奇观",
        "pages": [
            "https://www.michaelfrye.com/2016/06/07/magical-morning-redwoods/",
            "https://www.flickr.com/photos/nateroe/32786960890",
            "https://www.flickr.com/photos/ewoerlen/48132248106/",
            "https://www.grida.no/resources/1857",
            "https://meanderingwild.com/lava-fields-iceland/",
            "https://www.sandatlas.org/mossy-lava-field/",
            "https://www.amusingplanet.com/2017/09/the-mossy-lava-fields-of-iceland.html",
            "https://www.ashikaga.co.jp/fujinohana_special2026/en/",
            "https://www.japan-guide.com/e/e3850.html",
            "https://www.nps.gov/olym/learn/nature/temperate-rain-forests.htm",
            "https://parkscollecting.com/hoh-rainforest-hall-of-mosses-trail/",
            "https://sandatlas.org/malachite/",
            "https://hyperphysics.phy-astr.gsu.edu/hbase/Geophys/malachite.html",
            "https://www.hallerbos.be/en/",
            "https://shirshendusengupta.com/blog/hallerbos-magical-fairytale-bluebell-forest-halle-belgium",
            "https://waitomoglowwormcaves.org/",
            "https://www.atlasobscura.com/places/waitomo-glowworm-caves",
        ],
    },
}


def main():
    for topic, info in SCENE_PAGES.items():
        print(f"\n{'='*60}")
        print(f"Scene: {topic}")
        print(f"  {info['description']}")
        print(f"{'='*60}")

        sid = new_session()
        print(f"Session: {sid}")

        images = fetch_direct_image_urls(info["pages"], topic)
        save_session_data(sid, "search_results.json", images)

        print(f"\n=> Session: {sid}")
        print(f"   Total unique images: {len(images)}")
        print(f"   Topic: {topic}")
        print()

    print("\nAll scraping complete!")
    print("Next steps:")
    print("  1. Download: uv run python run.py download --session <sid>")
    print("  2. Dedup:    uv run python run.py dedup --session <sid>")
    print("  3. Analyze:  uv run python run.py analyze --session <sid> --model <model>")
    print("  4. Store:    uv run python run.py store --session <sid> --topic <topic>")
    print("  5. Gallery:  uv run python run.py gallery --topic <topic>")


if __name__ == "__main__":
    main()
