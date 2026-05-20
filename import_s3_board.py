"""Import S3_屏蔽室 images into new Board system.

Creates board from setting text, imports existing images with metadata,
runs rank (dedup + scoring), and generates composition.
"""
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from config import BOARDS_DIR, IMAGES_DIR, THUMBNAILS_DIR
from store.database import ImageDatabase
from models.schemas import (
    Board, BoardImage, VisualMetrics, CurationScores,
    ImageAnalysis, StyleProfile, BoardSection,
)

BOARD_ID = "S3_屏蔽室"
BOARD_NAME = "S3 屏蔽室·门内外"

SETTING_TEXT = """S3 · 屏蔽室·门内外

类型：室内·抽象·极简光
情绪：两个世界的交界、特权的孤独

场景描述：
一间社高层的私人屏蔽室。画面被一扇厚重的气密门一分为二——这是 Sonara 阶层分裂的终极视觉隐喻。门外是粗粝的工业世界，门内是无菌的孤岛。

构图：
画面左侧 40%（门外）：粗野主义混凝土走廊、矿尘覆盖的墙面、裸露的管道与阀门、铜锈藤从墙角蔓延、琥珀色阳光从走廊尽头小窗射入
画面右侧 60%（门内）：屏蔽室内部、六面沉声铜板材内壁（哑光拉丝）、全息影像终端在黑暗中散发幽蓝微光、均匀冷白荧光照明（无阴影死角）
气密门（画面正中偏左）：厚重的沉声铜门框、门半开——形成了"两个世界的交界线"

色彩方案：
门外：暖灰褐 #A09080 / 铜绿锈藤 #4A7C6F / 琥珀金 #E8C99B
门框：沉声铜暗红棕 #8B4513
门内：沉声铜哑光 #A0522D / 冷白荧光 #F0F0F0 / 幽蓝 #4060C0

光影：唯一光源在门外（橙矮星自然光）、门内均匀人工光、门框冷暖交界线是核心视觉点

情绪：孤独、洁净的压迫感。空间本身就是主角。

现实参考：粗野主义走廊、James Turrell 光空间装置、NASA 洁净室、安藤忠雄光之教堂"""

# Source collection data
COLLECTION_DIR = IMAGES_DIR / "S3_屏蔽室"
COLLECTION_JSON = COLLECTION_DIR / "_collection.json"


def main():
    print(f"=== Importing {BOARD_ID} into Board system ===", file=sys.stderr)

    # 1. Create board directory structure
    board_dir = BOARDS_DIR / BOARD_ID
    board_dir.mkdir(parents=True, exist_ok=True)
    (board_dir / "images").mkdir(exist_ok=True)
    (board_dir / "thumbnails").mkdir(exist_ok=True)
    print(f"Board dir: {board_dir}", file=sys.stderr)

    # 2. Copy images and thumbnails to board folder
    import shutil
    img_count = 0
    thumb_count = 0
    for f in COLLECTION_DIR.iterdir():
        if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
            # Copy image to board/images
            dest = board_dir / "images" / f.name
            if not dest.exists():
                shutil.copy2(f, dest)
            img_count += 1

            # Check if thumbnail exists
            thumb_name = f"thumb_{f.name}"
            thumb_src = THUMBNAILS_DIR / thumb_name
            if thumb_src.exists():
                thumb_dest = board_dir / "thumbnails" / thumb_name
                if not thumb_dest.exists():
                    shutil.copy2(thumb_src, thumb_dest)
                thumb_count += 1

    print(f"Copied {img_count} images, {thumb_count} thumbnails", file=sys.stderr)

    # 3. Load existing collection metadata
    collection_data = json.loads(COLLECTION_JSON.read_text(encoding="utf-8"))
    images_meta = {img["path"]: img for img in collection_data.get("images", [])}

    # 4. Create style profile from setting
    style_profile = StyleProfile(
        mood=["孤独", "压迫感", "两个世界的交界", "洁净", "极简"],
        color=["暖灰褐", "铜绿", "琥珀金", "冷白", "幽蓝", "暗红棕"],
        texture=["混凝土", "哑光拉丝铜", "矿尘", "无缝焊接"],
        lighting=["单一自然光源", "均匀冷白荧光", "冷暖交界线"],
        composition=["对称分割", "门框作为分界线", "极简空间"],
        era="90年代工业美学",
        medium="概念美术 / 室内场景",
    )

    # 5. Create Board
    db = ImageDatabase()

    # Delete existing board if any
    db._conn.execute("DELETE FROM board_images WHERE board_id = ?", (BOARD_ID,))
    db._conn.execute("DELETE FROM board_sections WHERE board_id = ?", (BOARD_ID,))
    db._conn.execute("DELETE FROM reference_tracks WHERE board_id = ?", (BOARD_ID,))
    db._conn.execute("DELETE FROM boards WHERE id = ?", (BOARD_ID,))
    db._conn.commit()

    board = Board(
        id=BOARD_ID,
        name=BOARD_NAME,
        base_dir=str(board_dir.resolve()),
        setting_text=SETTING_TEXT,
        visual_goal_summary="粗野主义与无菌空间的交界，门外暖灰褐铜绿，门内冷白幽蓝",
        style_profile=style_profile,
    )
    db.save_board(board)
    print(f"Board created: {BOARD_ID}", file=sys.stderr)

    # 6. Import images as BoardImage objects
    imported = 0
    for img_file in sorted((board_dir / "images").iterdir()):
        if not img_file.is_file() or img_file.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
            continue

        filename = img_file.name
        meta = images_meta.get(filename, {})

        # Build visual metrics from existing data
        vm_data = meta.get("visual_metrics", {})
        visual_metrics = VisualMetrics(
            brightness=vm_data.get("brightness", 0.5),
            saturation=vm_data.get("saturation", 0.3),
            warmth=vm_data.get("color_temperature", 0.5),
            contrast=vm_data.get("contrast", 0.4),
            color_complexity=vm_data.get("color_complexity", 0.5),
            edge_density=vm_data.get("edge_density", 0.3),
            texture_complexity=vm_data.get("texture_complexity", 0.2),
            spatial_openness=vm_data.get("spatial_openness", 0.5),
        )

        # Build curation scores (defaults from quality_score)
        q = meta.get("score", 7.0) / 10.0
        curation = CurationScores(
            aesthetic_score=q * 0.9,
            composition_score=q * 0.85,
            lighting_score=q * 0.8,
            design_reference_score=q * 0.75,
            style_consistency_score=q * 0.7,
            uniqueness_score=q * 0.6,
            usability_score=q * 0.8,
            risk_score=0.1,
        )

        # Build analysis
        analysis = ImageAnalysis(
            is_relevant=True,
            relevance_score=q * 0.8,  # Reasonable default for pre-curated images
            summary=meta.get("description", ""),
            style=meta.get("style", ""),
            mood=meta.get("mood", ""),
            composition_type=meta.get("composition", ""),
            key_elements=meta.get("tags", [])[:5],
            color_analysis="",
            strengths=[],
            weaknesses=[],
            relevance_to_setting="",
        )

        # Compute SHA256
        import hashlib
        sha256 = hashlib.sha256(img_file.read_bytes()).hexdigest()

        # Check thumbnail
        thumb_path = ""
        thumb_name = f"thumb_{filename}"
        thumb_file = board_dir / "thumbnails" / thumb_name
        if thumb_file.exists():
            thumb_path = f"thumbnails/{thumb_name}"

        board_img = BoardImage(
            id=Path(filename).stem,
            board_id=BOARD_ID,
            local_path=f"images/{filename}",
            thumb_path=thumb_path,
            filename=filename,
            description=meta.get("description", ""),
            tags=meta.get("tags", []),
            style=meta.get("style", ""),
            mood=meta.get("mood", ""),
            quality_score=meta.get("score", 7.0),
            status="candidate",
            visual_metrics=visual_metrics,
            curation_scores=curation,
            analysis=analysis,
            source_domain="legacy_import",
            sha256=sha256,
            file_size=img_file.stat().st_size,
        )

        db.add_board_image(BOARD_ID, board_img)
        imported += 1

    print(f"Imported {imported} images", file=sys.stderr)

    # 7. Export _board.json
    board_json = db.export_board_json(BOARD_ID)
    if board_json:
        (board_dir / "_board.json").write_text(board_json, encoding="utf-8")
        print(f"Exported _board.json", file=sys.stderr)

    db.close()
    print(f"\n=== Board '{BOARD_ID}' ready for rank/compose ===", file=sys.stderr)


if __name__ == "__main__":
    main()
