"""Assign functional categories to imported images based on tags/descriptions."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from store.database import ImageDatabase
from models.schemas import ImageCategoryScore

BOARD_ID = "S3_屏蔽室"

# Tag-based category mapping
CATEGORY_RULES = {
    "interior": ["interior", "corridor", "indoor", "church interior", "lounge", "museum interior",
                 "spacecraft interior", "exhibition", "cleanroom"],
    "architecture": ["architecture", "concrete", "building", "brutalist", "facade", "geometric",
                     "modern architecture", "concrete building", "concrete church", "stone house"],
    "mood": ["contemplative", "serene", "solemn", "mysterious", "surreal", "stark",
             "futuristic", "dreamlike", "oppressive", "lonely"],
    "color_lighting": ["neon light", "natural light", "lighting", "lens flare", "shadows",
                       "sunlight", "fluorescent", "blue", "pink", "glow"],
    "composition": ["perspective", "linear perspective", "symmetrical composition", "depth",
                    "tunnel", "geometric composition", "low-angle"],
    "tech_machinery": ["industrial", "equipment", "pipes", "machinery", "metal railings",
                       "grating", "wires", "technical"],
    "materials": ["concrete texture", "wood", "metal", "brick", "stone", "leather",
                  "textured background", "rust"],
    "props": ["sculpture", "chair", "display case", "artifacts", "furniture", "diorama"],
    "costume_character": ["portrait", "astronaut", "spacesuits", "hard hat", "beard",
                          "people", "man standing"],
    "landscape": ["garden", "trees", "sky", "outdoor", "lawn", "greenery"],
    "symbols_patterns": ["cross", "religious symbol", "religious cross", "mission patch"],
    "urban_layout": ["urban", "public space", "multi-level", "power lines", "urban landscape"],
}

def assign_categories():
    db = ImageDatabase()
    rows = db._conn.execute(
        "SELECT id, tags, description FROM board_images WHERE board_id = ?",
        (BOARD_ID,),
    ).fetchall()

    for img_id, tags_json, desc in rows:
        tags = json.loads(tags_json) if tags_json else []
        tag_lower = [t.lower() for t in tags]
        desc_lower = (desc or "").lower()

        categories = []
        for cat_id, keywords in CATEGORY_RULES.items():
            score = 0.0
            matched = []
            for kw in keywords:
                if kw.lower() in desc_lower or any(kw.lower() in t for t in tag_lower):
                    score += 0.3
                    matched.append(kw)
            if score > 0:
                score = min(1.0, score)
                categories.append(ImageCategoryScore(
                    category=cat_id,
                    score=score,
                    confidence=0.6,  # Tag-based, moderate confidence
                    reason=f"Matched tags: {', '.join(matched[:3])}",
                ))

        if not categories:
            # Default: mood + composition as fallback
            categories = [
                ImageCategoryScore(category="mood", score=0.4, confidence=0.3, reason="Default fallback"),
                ImageCategoryScore(category="composition", score=0.3, confidence=0.3, reason="Default fallback"),
            ]

        # Store categories
        cats_json = json.dumps([c.model_dump() for c in categories], ensure_ascii=False)
        db._conn.execute(
            "UPDATE board_images SET categories = ? WHERE id = ?",
            (cats_json, img_id),
        )
        print(f"  {img_id}: {[c.category for c in categories]}", file=sys.stderr)

    db._conn.commit()

    # Update _board.json
    from config import BOARDS_DIR
    board_json = db.export_board_json(BOARD_ID)
    if board_json:
        board_dir = BOARDS_DIR / BOARD_ID
        (board_dir / "_board.json").write_text(board_json, encoding="utf-8")

    db.close()
    print(f"\nCategories assigned to {len(rows)} images", file=sys.stderr)


if __name__ == "__main__":
    assign_categories()
