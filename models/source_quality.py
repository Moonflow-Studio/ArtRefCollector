"""Source domain quality scoring for image provenance."""

# Source quality tiers: S(0.9-1.0), A(0.75-0.89), B(0.55-0.74), C(0-0.54)
SOURCE_QUALITY_MAP: dict[str, float] = {
    # S-tier: professional art / museum / design portfolio
    "artstation.com": 0.95,
    "behance.net": 0.90,
    "deviantart.com": 0.82,
    "cgsociety.org": 0.88,
    "metmuseum.org": 0.92,
    "museum": 0.90,
    "archdaily.com": 0.88,
    "dezeen.com": 0.85,
    # A-tier: high-quality photo / commons / cultural
    "commons.wikimedia.org": 0.82,
    "wikimedia.org": 0.80,
    "unsplash.com": 0.78,
    "pexels.com": 0.76,
    "flickr.com": 0.78,
    "googleartsandculture.com": 0.85,
    "flickr": 0.76,
    "architectural-review.com": 0.82,
    # B-tier: social / generic search
    "pinterest.com": 0.62,
    "pinterest": 0.60,
    "reddit.com": 0.58,
    "redditstatic.com": 0.58,
    "tumblr.com": 0.60,
    "imgur.com": 0.55,
    "twitter.com": 0.55,
    "x.com": 0.55,
    "medium.com": 0.58,
    # C-tier: low quality / aggregators
    "pinimg.com": 0.50,
    "wp.com": 0.48,
    "blogspot.com": 0.45,
}

DEFAULT_SOURCE_SCORE = 0.45


def get_source_quality(domain: str) -> float:
    if not domain:
        return DEFAULT_SOURCE_SCORE
    domain = domain.lower().strip()
    # Exact match
    if domain in SOURCE_QUALITY_MAP:
        return SOURCE_QUALITY_MAP[domain]
    # Substring match (e.g. "i.pinimg.com" contains "pinimg.com")
    for key, score in SOURCE_QUALITY_MAP.items():
        if key in domain or domain.endswith(key):
            return score
    return DEFAULT_SOURCE_SCORE
