from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
IMAGES_DIR = DATA_DIR / "images"
THUMBNAILS_DIR = DATA_DIR / "thumbnails"
SESSIONS_DIR = DATA_DIR / "sessions"
FAISS_DIR = DATA_DIR / "faiss_index"
GALLERIES_DIR = DATA_DIR / "galleries"
DB_PATH = DATA_DIR / "art_ref.db"

DEFAULT_API_BASE = "http://localhost:23333"
DEFAULT_MODEL = "zhipu:glm-4.6v"
DEFAULT_MAX_RESULTS = 30
DEFAULT_DEDUP_THRESHOLD = 0.92
DEFAULT_PHASH_HAMMING = 10
DEFAULT_CONCURRENT_DOWNLOADS = 5
DEFAULT_MIN_FILE_SIZE = 10240
DEFAULT_THUMBNAIL_SIZE = (300, 300)

VISION_PROMPT = """Analyze this image as an art reference. Return a JSON object with these fields:
- "description": A detailed description of the image content (1-2 sentences)
- "tags": Array of relevant tags (5-10 tags, lowercase, covering subject, style, technique)
- "style": The art style or medium (e.g., "digital painting", "photography", "concept art")
- "color_palette": Array of dominant colors (3-5 colors, descriptive names)
- "mood": The emotional tone or atmosphere
- "composition": Composition type (e.g., "wide shot", "close-up", "bird's eye view")
- "quality_score": Art reference value score 1-10 (consider uniqueness, detail, usefulness as reference)
- "use_cases": Array of potential use cases (e.g., "character design", "lighting reference")

Return ONLY valid JSON, no other text."""
