"""Board Ranker — dedup, score, and assign status for board images.

Three-tier dedup:
  1. SHA256 exact dedup
  2. pHash perceptual dedup
  3. CLIP semantic dedup

Dimension-distance scoring + status assignment (v5).
"""

import hashlib
import math
import sys
from pathlib import Path

import numpy as np
from tqdm import tqdm

from config import DISTANCE_SCORING_DEFAULTS, STATUS_RULES_V2
from models.schemas import (
    BoardCenterValues,
    BoardImage,
    DimensionCenter,
    PerceptualDimensions,
    PixelMetrics,
)


# ---------------------------------------------------------------------------
# SHA256 computation
# ---------------------------------------------------------------------------

def compute_sha256(file_path: str) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Three-tier dedup
# ---------------------------------------------------------------------------

def dedup_sha256(images: list[BoardImage], db) -> int:
    """Tier 1: exact SHA256 dedup. Mark duplicates, return count removed."""
    removed = 0
    for img in images:
        if img.status == "duplicate" or not img.local_path:
            continue
        # Compute sha256 if missing
        if not img.sha256 and Path(img.local_path).exists():
            img.sha256 = compute_sha256(img.local_path)

        if img.sha256:
            existing = db.find_duplicate_by_sha256(img.board_id, img.sha256)
            if existing and existing.id != img.id:
                img.status = "duplicate"
                img.duplicate_penalty = 1.0
                db.update_image_status(img.id, "duplicate")
                removed += 1
    return removed


def dedup_phash(images: list[BoardImage], db, threshold: int = 10) -> int:
    """Tier 2: perceptual hash dedup. Return count removed."""
    removed = 0
    for img in images:
        if img.status == "duplicate" or not img.phash:
            continue
        similar = db.find_similar_by_phash(img.board_id, img.phash, threshold)
        for s in similar:
            if s.id != img.id and s.status != "duplicate":
                # Keep the one with higher dimension_distance_score
                s_score = s.dimension_distance_score
                img_score = img.dimension_distance_score
                if img_score > s_score:
                    s.status = "duplicate"
                    s.duplicate_penalty = 0.85
                    db.update_image_scores(s.id, s.final_score, 0.85, "duplicate")
                    removed += 1
                elif s_score > img_score:
                    img.status = "duplicate"
                    img.duplicate_penalty = 0.85
                    db.update_image_scores(img.id, img.final_score, 0.85, "duplicate")
                    removed += 1
                    break
    return removed


def dedup_clip(images: list[BoardImage], threshold: float = 0.92) -> int:
    """Tier 3: CLIP semantic dedup. Return count removed."""
    valid = [img for img in images if img.status != "duplicate" and img.local_path
             and Path(img.local_path).exists()]
    if len(valid) < 2:
        return 0

    from store.embedding_utils import encode_image
    embeddings = []
    for img in tqdm(valid, desc="Computing CLIP embeddings for dedup"):
        try:
            emb = encode_image(img.local_path)
            embeddings.append(emb / np.linalg.norm(emb) if emb is not None else None)
        except Exception:
            embeddings.append(None)

    removed = 0
    for i in range(len(valid)):
        if valid[i].status == "duplicate" or embeddings[i] is None:
            continue
        for j in range(i + 1, len(valid)):
            if valid[j].status == "duplicate" or embeddings[j] is None:
                continue
            sim = float(np.dot(embeddings[i], embeddings[j]))
            if sim >= threshold:
                # Keep higher dimension_distance_score
                si = valid[i].dimension_distance_score
                sj = valid[j].dimension_distance_score
                if si >= sj:
                    loser = valid[j]
                else:
                    loser = valid[i]
                loser.status = "duplicate"
                loser.duplicate_penalty = min(sim, 1.0)
                removed += 1
    return removed


# ---------------------------------------------------------------------------
# Dimension-distance scoring (v5)
# ---------------------------------------------------------------------------

def compute_dimension_distance_score(
    img: BoardImage,
    center_values: BoardCenterValues | None = None,
) -> float:
    """Score based on distance from center values using Gaussian decay.

    Returns 0-1 score. Higher = closer to center values = better match.
    """
    defaults = DISTANCE_SCORING_DEFAULTS

    if not center_values or not center_values.centers:
        # No center values defined: use relevance as base, neutral dimension score
        relevance = img.analysis.relevance_score if img.analysis else 0.5
        return relevance

    # Build lookup from image's dimension values
    pd = img.perceptual_dimensions
    px = img.pixel_metrics
    all_dims: dict[str, float] = {}
    for field_name in PerceptualDimensions.model_fields:
        all_dims[field_name] = getattr(pd, field_name, 0.5)
    # Pixel dimensions that may also have center targets
    for field_name in ("brightness", "saturation", "color_temperature",
                        "contrast", "color_complexity", "spatial_openness"):
        all_dims[field_name] = getattr(px, field_name, 0.5)

    total_weight = 0.0
    weighted_score = 0.0

    for dc in center_values.centers:
        val = all_dims.get(dc.dimension)
        if val is None:
            continue
        distance = abs(val - dc.center)
        # Gaussian decay: score = exp(-(distance/tolerance)^2)
        dim_score = math.exp(-((distance / dc.tolerance) ** 2))
        weighted_score += dim_score * dc.weight
        total_weight += dc.weight

    if total_weight == 0:
        return 0.5

    base_score = weighted_score / total_weight

    # Combine with relevance
    relevance = img.analysis.relevance_score if img.analysis else 0.5
    risk = img.curation_scores.risk_score
    dup_penalty = img.duplicate_penalty

    combined = (
        defaults["relevance_weight"] * relevance
        + defaults["dimension_weight"] * base_score
        - defaults["risk_penalty"] * risk
        - defaults["duplicate_penalty"] * dup_penalty
    )
    return max(0.0, min(1.0, combined))


# Legacy compat
def compute_final_score(img: BoardImage) -> float:
    """Legacy wrapper — delegates to dimension-distance scoring."""
    return compute_dimension_distance_score(img)


# ---------------------------------------------------------------------------
# Status assignment (v5)
# ---------------------------------------------------------------------------

def assign_status_v2(img: BoardImage, distance_score: float) -> str:
    """Determine image status based on dimension-distance score."""
    rules = STATUS_RULES_V2
    analysis = img.analysis

    if img.status == "duplicate":
        return "duplicate"

    if analysis and not analysis.is_relevant:
        return "rejected"
    if analysis and analysis.final_recommendation == "reject":
        return "rejected"

    relevance = analysis.relevance_score if analysis else 0.5

    reject_rule = rules.get("rejected", {})
    if relevance < reject_rule.get("min_relevance", 0.40):
        return "rejected"

    # Core
    core_rule = rules.get("core", {})
    if (distance_score >= core_rule.get("min_score", 0.85)
            and relevance >= core_rule.get("min_relevance", 0.75)):
        return "core"

    # Curated
    curated_rule = rules.get("curated", {})
    if distance_score >= curated_rule.get("min_score", 0.70):
        return "curated"

    # Outlier: high relevance but low dimension match
    outlier_rule = rules.get("outlier", {})
    if (distance_score < outlier_rule.get("max_dimension_match", 0.40)
            and relevance >= outlier_rule.get("min_relevance", 0.65)):
        return "outlier"

    # Supplement
    supplement_rule = rules.get("supplement", {})
    if distance_score >= supplement_rule.get("min_score", 0.55):
        return "supplement"

    return "rejected"


# Legacy wrapper
def assign_status(img: BoardImage, final_score: float) -> str:
    return assign_status_v2(img, final_score)


# ---------------------------------------------------------------------------
# Main rank function
# ---------------------------------------------------------------------------

def rank_board_images(
    board_id: str,
    phash_threshold: int = 10,
    clip_threshold: float = 0.92,
    use_clip: bool = False,
) -> dict:
    """Run full dedup + dimension-distance score + status pipeline for a board."""
    from store.database import ImageDatabase

    db = ImageDatabase()
    board = db.get_board(board_id)
    if not board:
        print(f"Board {board_id} not found", file=sys.stderr)
        db.close()
        return {"error": f"Board {board_id} not found"}

    images = db.get_board_images(board_id)
    total = len(images)

    # Phase 1: Compute SHA256 for images missing it
    for img in tqdm(images, desc="Computing SHA256"):
        if not img.sha256 and img.local_path and Path(img.local_path).exists():
            img.sha256 = compute_sha256(img.local_path)

    # Phase 2: Three-tier dedup
    sha256_removed = dedup_sha256(images, db)
    phash_removed = dedup_phash(images, db, phash_threshold)
    clip_removed = dedup_clip(images, clip_threshold) if use_clip else 0

    # Derive center values if not already present
    center_values = board.center_values
    if not center_values.centers and board.setting_text:
        try:
            from analyze.setting_parser import derive_center_values
            print("No center values found — deriving from setting text...")
            center_values = derive_center_values(board.setting_text)
            board.center_values = center_values
            db.save_board(board)
        except Exception as e:
            print(f"Failed to derive center values: {e}", file=sys.stderr)

    # Phase 3: Compute dimension-distance scores
    for img in images:
        if img.status == "duplicate":
            continue
        distance_score = compute_dimension_distance_score(img, center_values)
        status = assign_status_v2(img, distance_score)
        img.dimension_distance_score = distance_score
        img.final_score = distance_score  # Keep legacy field in sync
        img.status = status
        db.update_image_scores(img.id, distance_score, img.duplicate_penalty, status)
        db.update_image_dimension_score(img.id, distance_score)

    # Update _board.json
    board_json = db.export_board_json(board_id)
    if board_json and board.base_dir:
        board_path = Path(board.base_dir) / "_board.json"
        board_path.write_text(board_json, encoding="utf-8")

    # Stats
    remaining = db.get_board_images(board_id)
    status_counts = {}
    for img in remaining:
        status_counts[img.status] = status_counts.get(img.status, 0) + 1

    db.close()

    return {
        "board_id": board_id,
        "total_images": total,
        "sha256_duplicates": sha256_removed,
        "phash_duplicates": phash_removed,
        "clip_duplicates": clip_removed,
        "status_distribution": status_counts,
        "center_values_source": center_values.source,
        "center_values_count": len(center_values.centers),
    }
