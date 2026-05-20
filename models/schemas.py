"""Pydantic schemas for Board, ReferenceTrack, Image and related types."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums / Constants
# ---------------------------------------------------------------------------

IMAGE_STATUSES = [
    "candidate",   # 候选池图片
    "filtered",    # 通过基础过滤
    "curated",     # 进入主画板
    "core",        # 核心参考图
    "anti",        # 负面参考图
    "rejected",    # 被拒绝
    "duplicate",   # 重复图
    "outlier",     # 风格离群图
]

SOURCE_TYPES = [
    "real_world_location",
    "real_world_object",
    "architecture_style",
    "historical_period",
    "cultural_reference",
    "religious_reference",
    "game_reference",
    "film_reference",
    "concept_art_reference",
    "material_reference",
    "costume_reference",
    "environment_reference",
    "color_lighting_reference",
    "composition_reference",
    "anti_reference",
]


# ---------------------------------------------------------------------------
# Shared sub-models
# ---------------------------------------------------------------------------

class FunctionalCategory(BaseModel):
    id: str
    name: str
    description: str


class ImageCategoryScore(BaseModel):
    category: str
    score: float = Field(ge=0.0, le=1.0)
    reason: str = ""


class StyleProfile(BaseModel):
    mood: list[str] = []
    architecture: list[str] = []
    color: list[str] = []
    materials: list[str] = []
    lighting: list[str] = []
    composition: list[str] = []
    avoid: list[str] = []


class VisualMetrics(BaseModel):
    brightness: float = Field(default=0.5, ge=0.0, le=1.0)
    saturation: float = Field(default=0.5, ge=0.0, le=1.0)
    warmth: float = Field(default=0.5, ge=0.0, le=1.0)
    contrast: float = Field(default=0.5, ge=0.0, le=1.0)
    color_complexity: float = Field(default=0.5, ge=0.0, le=1.0)
    detail_density: float = Field(default=0.5, ge=0.0, le=1.0)
    shot_scale: float = Field(default=0.5, ge=0.0, le=1.0)
    openness: float = Field(default=0.5, ge=0.0, le=1.0)
    monumentality: float = Field(default=0.5, ge=0.0, le=1.0)
    religiousness: float = Field(default=0.5, ge=0.0, le=1.0)
    industrialness: float = Field(default=0.5, ge=0.0, le=1.0)
    decay: float = Field(default=0.5, ge=0.0, le=1.0)
    orderliness: float = Field(default=0.5, ge=0.0, le=1.0)
    fantasy_level: float = Field(default=0.5, ge=0.0, le=1.0)
    sci_fi_level: float = Field(default=0.5, ge=0.0, le=1.0)


class CurationScores(BaseModel):
    aesthetic_score: float = Field(default=0.0, ge=0.0, le=1.0)
    composition_score: float = Field(default=0.0, ge=0.0, le=1.0)
    lighting_score: float = Field(default=0.0, ge=0.0, le=1.0)
    design_reference_score: float = Field(default=0.0, ge=0.0, le=1.0)
    style_consistency_score: float = Field(default=0.0, ge=0.0, le=1.0)
    uniqueness_score: float = Field(default=0.0, ge=0.0, le=1.0)
    usability_score: float = Field(default=0.0, ge=0.0, le=1.0)
    risk_score: float = Field(default=0.0, ge=0.0, le=1.0)


class ImageAnalysis(BaseModel):
    is_relevant: bool = True
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    functional_categories: list[ImageCategoryScore] = []
    visual_summary: str = ""
    useful_elements: list[str] = []
    style_tags: list[str] = []
    material_tags: list[str] = []
    color_palette_words: list[str] = []
    composition_tags: list[str] = []
    possible_risks: list[str] = []
    avoid_copying: list[str] = []
    recommended_board_section: list[str] = []
    final_recommendation: str = "reference"  # core/reference/supplement/reject


class SourceQualityScore(BaseModel):
    domain: str
    score: float = Field(ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# BoardImage — enriched image record
# ---------------------------------------------------------------------------

class BoardImage(BaseModel):
    id: str = Field(default_factory=lambda: "")
    board_id: str = ""
    track_id: str = ""
    local_path: str = ""
    thumb_path: str = ""
    source_url: str = ""
    page_url: str = ""
    source_domain: str = ""
    source_query: str = ""
    width: int = 0
    height: int = 0
    file_size: int = 0
    sha256: str = ""
    phash: str = ""
    status: str = "candidate"
    categories: list[ImageCategoryScore] = []
    visual_metrics: VisualMetrics = Field(default_factory=VisualMetrics)
    curation_scores: CurationScores = Field(default_factory=CurationScores)
    analysis: ImageAnalysis = Field(default_factory=ImageAnalysis)
    source_quality_score: float = Field(default=0.45, ge=0.0, le=1.0)
    final_score: float = Field(default=0.0, ge=0.0, le=1.0)
    duplicate_penalty: float = Field(default=0.0, ge=0.0, le=1.0)
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())

    # Legacy compatibility fields
    filename: str = ""
    description: str = ""
    tags: list[str] = []
    style: str = ""
    color_palette: list[str] = []
    mood: str = ""
    composition: str = ""
    quality_score: float = 0.0
    use_cases: list[str] = []


# ---------------------------------------------------------------------------
# ReferenceTrack
# ---------------------------------------------------------------------------

class ReferenceTrack(BaseModel):
    id: str = ""
    board_id: str = ""
    name: str
    description: str = ""
    source_type: str = "real_world_reference"
    target_categories: list[str] = []
    search_queries: list[str] = []
    negative_queries: list[str] = Field(default_factory=lambda: [
        "cartoon", "anime", "logo", "product", "meme",
        "low resolution", "stock photo", "watermark", "toy",
    ])
    expected_visual_features: list[str] = []
    relation_to_setting: str = ""


# ---------------------------------------------------------------------------
# BoardSection — functional category section in a composed board
# ---------------------------------------------------------------------------

class KeyImageRef(BaseModel):
    image_id: str
    reason: str = ""


class BoardSection(BaseModel):
    section_id: str
    section_name: str
    summary: str = ""
    design_takeaways: list[str] = []
    key_images: list[KeyImageRef] = []
    supporting_images: list[KeyImageRef] = []
    anti_references: list[KeyImageRef] = []
    missing_needs: list[str] = []


# ---------------------------------------------------------------------------
# Board — top-level entity
# ---------------------------------------------------------------------------

class Board(BaseModel):
    id: str = ""  # Human-readable name, used as folder name
    name: str
    base_dir: str = ""  # Absolute path to the board folder
    setting_text: str = ""
    visual_goal_summary: str = ""
    style_profile: StyleProfile = Field(default_factory=StyleProfile)
    reference_tracks: list[ReferenceTrack] = []
    images: list[BoardImage] = []
    sections: list[BoardSection] = []
    core_references: list[KeyImageRef] = []
    anti_references: list[KeyImageRef] = []
    global_missing_needs: list[str] = []
    next_search_suggestions: list[str] = []
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())

    def get_images_dir(self) -> Path:
        """Absolute path to board's images/ directory."""
        from pathlib import Path
        return Path(self.base_dir) / "images" if self.base_dir else Path("")

    def get_thumbs_dir(self) -> Path:
        """Absolute path to board's thumbnails/ directory."""
        from pathlib import Path
        return Path(self.base_dir) / "thumbnails" if self.base_dir else Path("")

    def resolve_image_path(self, relative_path: str) -> str:
        """Resolve a relative image path to absolute using base_dir."""
        if not self.base_dir:
            return relative_path
        return str(Path(self.base_dir) / relative_path)

    def make_relative(self, abs_path: str) -> str:
        """Convert an absolute path under base_dir to relative."""
        if not self.base_dir or not abs_path:
            return abs_path
        try:
            return str(Path(abs_path).relative_to(self.base_dir))
        except ValueError:
            return abs_path


# ---------------------------------------------------------------------------
# Setting Parse result
# ---------------------------------------------------------------------------

class SettingParseResult(BaseModel):
    core_concepts: list[str] = []
    visual_dimensions: list[str] = []
    known_references: list[str] = []
    implicit_references: list[str] = []
    missing_references: list[str] = []
    style_profile: StyleProfile = Field(default_factory=StyleProfile)
    avoid_directions: list[str] = []
    clarification_questions: list[str] = []
