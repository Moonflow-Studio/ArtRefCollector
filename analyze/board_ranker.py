"""Board Ranker — dedup, score, and assign status for board images.

Three-tier dedup:
  1. SHA256 exact dedup
  2. pHash perceptual dedup
  3. CLIP semantic dedup

Composite scoring + status assignment.
"""

import hashlib
import sys
from pathlib import Path

import numpy as np
from tqdm import tqdm

from config import RANKING_WEIGHTS, STATUS_RULES
from models.schemas import BoardImage, CurationScores


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
                # Keep the one with higher score
                s_score = s.curation_scores.design_reference_score
                img_score = img.curation_scores.design_reference_score
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
                # Keep higher design_reference_score
                si = valid[i].curation_scores.design_reference_score
                sj = valid[j].curation_scores.design_reference_score
                if si >= sj:
                    loser = valid[j]
                else:
                    loser = valid[i]
                loser.status = "duplicate"
                loser.duplicate_penalty = min(sim, 1.0)
                removed += 1
    return removed


# ---------------------------------------------------------------------------
# Composite scoring
# ---------------------------------------------------------------------------

def compute_final_score(img: BoardImage) -> float:
    """Compute weighted final score from curation scores + metadata."""
    cs = img.curation_scores
    w = RANKING_WEIGHTS
    score = (
        w["relevance"] * (img.analysis.relevance_score if img.analysis else 0.0)
        + w["design_reference"] * cs.design_reference_score
        + w["aesthetic"] * cs.aesthetic_score
        + w["composition"] * cs.composition_score
        + w["lighting"] * cs.lighting_score
        + w["style_consistency"] * cs.style_consistency_score
        + w["usability"] * cs.usability_score
        + w["uniqueness"] * cs.uniqueness_score
        + w["source_quality"] * img.source_quality_score
        - w["risk_penalty"] * cs.risk_score
        - w["duplicate_penalty"] * img.duplicate_penalty
    )
    return max(0.0, min(1.0, score))


# ---------------------------------------------------------------------------
# Status assignment
# ---------------------------------------------------------------------------

def assign_status(img: BoardImage, final_score: float) -> str:
    """Determine image status based on scores and rules."""
    cs = img.curation_scores
    analysis = img.analysis
    rules = STATUS_RULES

    # Already duplicate
    if img.status == "duplicate":
        return "duplicate"

    # Rejected
    if analysis and not analysis.is_relevant:
        return "rejected"
    if analysis and analysis.final_recommendation == "reject":
        return "rejected"

    relevance = analysis.relevance_score if analysis else 0.5
    design_ref = cs.design_reference_score

    reject_rule = rules.get("rejected", {})
    if relevance < reject_rule.get("min_relevance", 0.45):
        return "rejected"
    if design_ref < reject_rule.get("min_design_reference", 0.35):
        return "rejected"

    # Core
    core_rule = rules.get("core", {})
    if (final_score >= core_rule.get("min_final_score", 0.82)
            and cs.style_consistency_score >= core_rule.get("min_style_consistency", 0.70)):
        return "core"

    # Curated
    curated_rule = rules.get("curated", {})
    if final_score >= curated_rule.get("min_final_score", 0.68):
        return "curated"

    # Outlier
    outlier_rule = rules.get("outlier", {})
    if (cs.style_consistency_score <= outlier_rule.get("max_style_consistency", 0.40)
            and relevance >= outlier_rule.get("min_relevance", 0.60)):
        return "outlier"

    # Supplement
    supplement_rule = rules.get("supplement", {})
    if final_score >= supplement_rule.get("min_final_score", 0.50):
        return "supplement"

    return "rejected"


# ---------------------------------------------------------------------------
# Main rank function
# ---------------------------------------------------------------------------

def rank_board_images(
    board_id: str,
    phash_threshold: int = 10,
    clip_threshold: float = 0.92,
    use_clip: bool = False,
) -> dict:
    """Run full dedup + score + status pipeline for a board."""
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

    # Phase 3: Compute final scores
    for img in images:
        if img.status == "duplicate":
            continue
        final_score = compute_final_score(img)
        status = assign_status(img, final_score)
        img.final_score = final_score
        img.status = status
        db.update_image_scores(img.id, final_score, img.duplicate_penalty, status)

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
    }
