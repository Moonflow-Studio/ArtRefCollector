import os
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
IMAGES_DIR = DATA_DIR / "images"
THUMBNAILS_DIR = DATA_DIR / "thumbnails"
SESSIONS_DIR = DATA_DIR / "sessions"
METRICS_DIR = DATA_DIR / "metrics"
FAISS_DIR = DATA_DIR / "faiss_index"
LANCEDB_DIR = DATA_DIR / "lancedb"
GALLERIES_DIR = DATA_DIR / "galleries"
BOARDS_DIR = DATA_DIR / "boards"
DB_PATH = DATA_DIR / "art_ref.db"
VLM_CONFIG_PATH = DATA_DIR / "vlm_config.json"

DEFAULT_API_BASE = "http://localhost:23333"
DEFAULT_MODEL = "zhipu:glm-4.6v"
DEFAULT_MAX_RESULTS = 30
DEFAULT_DEDUP_THRESHOLD = 0.92
DEFAULT_PHASH_HAMMING = 10
DEFAULT_CONCURRENT_DOWNLOADS = 5
DEFAULT_MIN_FILE_SIZE = 10240
DEFAULT_THUMBNAIL_SIZE = (300, 300)

# Search backend
SEARXNG_BASE_URL = os.environ.get("ARTREF_SEARXNG_URL", "")
DEFAULT_SEARCH_BACKEND = os.environ.get("ARTREF_SEARCH_BACKEND", "auto")

# Download backend
DEFAULT_DOWNLOAD_BACKEND = os.environ.get("ARTREF_DOWNLOAD_BACKEND", "auto")
IMG2DATASET_FALLBACK = True

# Vector store backend
DEFAULT_VECTOR_BACKEND = os.environ.get("ARTREF_VECTOR_BACKEND", "faiss")

# Ranking weights for final_score computation (legacy, used only for backward compat)
RANKING_WEIGHTS = {
    "relevance": 0.18,
    "design_reference": 0.16,
    "aesthetic": 0.14,
    "composition": 0.10,
    "lighting": 0.10,
    "style_consistency": 0.14,
    "usability": 0.08,
    "uniqueness": 0.06,
    "source_quality": 0.04,
    "risk_penalty": 0.08,
    "duplicate_penalty": 0.10,
}

# Distance-based scoring defaults (v5)
DISTANCE_SCORING_DEFAULTS = {
    "relevance_weight": 0.4,
    "dimension_weight": 0.6,
    "risk_penalty": 0.15,
    "duplicate_penalty": 0.20,
}

# Status determination thresholds (legacy)
STATUS_RULES = {
    "core": {"min_final_score": 0.82, "min_style_consistency": 0.70},
    "curated": {"min_final_score": 0.68},
    "supplement": {"min_final_score": 0.50},
    "outlier": {"max_style_consistency": 0.40, "min_relevance": 0.60},
    "rejected": {"min_relevance": 0.45, "min_design_reference": 0.35},
    "duplicate": {"min_duplicate_penalty": 0.80},
}

# Status determination thresholds (v5 — dimension-distance scoring)
STATUS_RULES_V2 = {
    "core": {"min_score": 0.70, "min_relevance": 0.70},
    "curated": {"min_score": 0.55},
    "supplement": {"min_score": 0.38},
    "outlier": {"max_dimension_match": 0.25, "min_relevance": 0.60},
    "rejected": {"min_relevance": 0.30},
    "duplicate": {"min_duplicate_penalty": 0.80},
}

# Perceptual dimension definitions — label and axis description for UI and VLM prompt
PERCEPTUAL_DIMENSION_DEFS = {
    "shot_scale":          {"label": "景别",       "axis": "远景 → 特写",        "label_low": "远景",   "label_high": "特写"},
    "spatial_scale":       {"label": "空间尺度",   "axis": "私密 → 宏大",        "label_low": "私密",   "label_high": "宏大"},
    "openness":            {"label": "开放感",     "axis": "封闭 → 开阔",        "label_low": "封闭",   "label_high": "开阔"},
    "style":               {"label": "风格化",     "axis": "写实 → 风格化",      "label_low": "写实",   "label_high": "风格化"},
    "ornateness":          {"label": "装饰度",     "axis": "朴素 → 华丽",        "label_low": "朴素",   "label_high": "华丽"},
    "orderliness":         {"label": "秩序感",     "axis": "混乱 → 规整",        "label_low": "混乱",   "label_high": "规整"},
    "emotion_intensity":   {"label": "情绪强度",   "axis": "平静 → 强烈",        "label_low": "平静",   "label_high": "强烈"},
    "warmth":              {"label": "色温氛围",   "axis": "冷酷 → 温暖",        "label_low": "冷酷",   "label_high": "温暖"},
    "material_roughness":  {"label": "材质粗度",   "axis": "精致 → 粗粝",        "label_low": "精致",   "label_high": "粗粝"},
    "decay":               {"label": "破败度",     "axis": "完好 → 破败",        "label_low": "完好",   "label_high": "破败"},
    "era_feel":            {"label": "时代感",     "axis": "古典 → 未来",        "label_low": "古典",   "label_high": "未来"},
    "industrialness":      {"label": "工业感",     "axis": "自然 → 工业",        "label_low": "自然",   "label_high": "工业"},
    "religiousness":       {"label": "宗教感",     "axis": "世俗 → 神圣",        "label_low": "世俗",   "label_high": "神圣"},
    "fantasy_level":       {"label": "奇幻程度",   "axis": "现实 → 奇幻",        "label_low": "现实",   "label_high": "奇幻"},
    "sci_fi_level":        {"label": "科幻程度",   "axis": "现实 → 科幻",        "label_low": "现实",   "label_high": "科幻"},
}

# Pixel metric definitions — label and axis for UI
PIXEL_METRIC_DEFS = {
    "brightness":          {"label": "亮度",       "axis": "暗 → 亮"},
    "saturation":          {"label": "饱和度",     "axis": "灰 → 鲜艳"},
    "color_temperature":   {"label": "色温",       "axis": "冷 → 暖"},
    "dominant_hue":        {"label": "主色调",     "axis": "蓝绿 → 红黄"},
    "contrast":            {"label": "对比度",     "axis": "柔和 → 强对比"},
    "color_complexity":    {"label": "色彩丰富度", "axis": "单纯 → 丰富"},
    "edge_density":        {"label": "边缘密度",   "axis": "简洁 → 复杂"},
    "texture_complexity":  {"label": "纹理复杂度", "axis": "平滑 → 粗糙"},
    "spatial_openness":    {"label": "空间开放度", "axis": "封闭 → 开阔"},
}

# Board defaults
DEFAULT_BOARD_TOP_K = {
    "core_references": 8,
    "section_key_images": 8,
    "section_supporting": 16,
    "anti_references": 8,
}

# Gallery images per track search
IMAGES_PER_TRACK = 15

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
