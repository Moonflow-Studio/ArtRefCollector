"""SQLite database with Board/Track/Image tables."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from config import DB_PATH

# Import schemas for type hints only
from models.schemas import (
    Board,
    BoardImage,
    BoardSection,
    CurationScores,
    ImageAnalysis,
    ImageCategoryScore,
    KeyImageRef,
    ReferenceTrack,
    StyleProfile,
    VisualMetrics,
)
from models.source_quality import get_source_quality


def _json_dumps(obj: Any) -> str:
    if obj is None:
        return ""
    if isinstance(obj, (list, dict)):
        return json.dumps(obj, ensure_ascii=False)
    return str(obj)


def _json_loads_list(val: str | None) -> list:
    if not val:
        return []
    try:
        result = json.loads(val)
        return result if isinstance(result, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _json_loads_dict(val: str | None) -> dict:
    if not val:
        return {}
    try:
        result = json.loads(val)
        return result if isinstance(result, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


class ImageDatabase:
    SCHEMA_VERSION = 2

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or str(DB_PATH)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_tables()
        self._migrate()

    def _init_tables(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS schema_meta (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS boards (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                setting_text TEXT DEFAULT '',
                visual_goal_summary TEXT DEFAULT '',
                style_profile TEXT DEFAULT '{}',
                global_missing_needs TEXT DEFAULT '[]',
                next_search_suggestions TEXT DEFAULT '[]',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS reference_tracks (
                id TEXT PRIMARY KEY,
                board_id TEXT NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                source_type TEXT DEFAULT '',
                target_categories TEXT DEFAULT '[]',
                search_queries TEXT DEFAULT '[]',
                negative_queries TEXT DEFAULT '[]',
                expected_visual_features TEXT DEFAULT '[]',
                relation_to_setting TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS board_images (
                id TEXT PRIMARY KEY,
                board_id TEXT NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
                track_id TEXT DEFAULT '' REFERENCES reference_tracks(id) ON DELETE SET NULL,
                local_path TEXT NOT NULL,
                thumb_path TEXT DEFAULT '',
                source_url TEXT DEFAULT '',
                page_url TEXT DEFAULT '',
                source_domain TEXT DEFAULT '',
                source_query TEXT DEFAULT '',
                width INTEGER DEFAULT 0,
                height INTEGER DEFAULT 0,
                file_size INTEGER DEFAULT 0,
                sha256 TEXT DEFAULT '',
                phash TEXT DEFAULT '',
                status TEXT DEFAULT 'candidate',
                categories TEXT DEFAULT '[]',
                visual_metrics TEXT DEFAULT '{}',
                curation_scores TEXT DEFAULT '{}',
                analysis TEXT DEFAULT '{}',
                source_quality_score REAL DEFAULT 0.45,
                final_score REAL DEFAULT 0.0,
                duplicate_penalty REAL DEFAULT 0.0,
                -- legacy compatibility
                filename TEXT DEFAULT '',
                description TEXT DEFAULT '',
                tags TEXT DEFAULT '',
                style TEXT DEFAULT '',
                color_palette TEXT DEFAULT '',
                mood TEXT DEFAULT '',
                composition TEXT DEFAULT '',
                quality_score REAL DEFAULT 0,
                use_cases TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS board_sections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                board_id TEXT NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
                section_id TEXT NOT NULL,
                section_name TEXT NOT NULL,
                summary TEXT DEFAULT '',
                design_takeaways TEXT DEFAULT '[]',
                key_images TEXT DEFAULT '[]',
                supporting_images TEXT DEFAULT '[]',
                anti_references TEXT DEFAULT '[]',
                missing_needs TEXT DEFAULT '[]',
                UNIQUE(board_id, section_id)
            );

            CREATE INDEX IF NOT EXISTS idx_tracks_board ON reference_tracks(board_id);
            CREATE INDEX IF NOT EXISTS idx_images_board ON board_images(board_id);
            CREATE INDEX IF NOT EXISTS idx_images_track ON board_images(track_id);
            CREATE INDEX IF NOT EXISTS idx_images_status ON board_images(status);
            CREATE INDEX IF NOT EXISTS idx_images_phash ON board_images(phash);
            CREATE INDEX IF NOT EXISTS idx_images_sha256 ON board_images(sha256);
            CREATE INDEX IF NOT EXISTS idx_images_score ON board_images(final_score);
            CREATE INDEX IF NOT EXISTS idx_sections_board ON board_sections(board_id);

            -- Legacy tables (kept for backward compatibility)
            CREATE TABLE IF NOT EXISTS collections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                description TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                collection_id INTEGER REFERENCES collections(id) ON DELETE CASCADE,
                filename TEXT NOT NULL,
                original_url TEXT DEFAULT '',
                source TEXT DEFAULT '',
                local_path TEXT NOT NULL,
                thumbnail_path TEXT DEFAULT '',
                width INTEGER DEFAULT 0,
                height INTEGER DEFAULT 0,
                file_size INTEGER DEFAULT 0,
                phash TEXT DEFAULT '',
                description TEXT DEFAULT '',
                tags TEXT DEFAULT '',
                style TEXT DEFAULT '',
                color_palette TEXT DEFAULT '',
                mood TEXT DEFAULT '',
                composition TEXT DEFAULT '',
                quality_score REAL DEFAULT 0,
                use_cases TEXT DEFAULT '',
                status TEXT DEFAULT 'active',
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_images_collection ON images(collection_id);
            CREATE INDEX IF NOT EXISTS idx_images_tags ON images(tags);
            CREATE INDEX IF NOT EXISTS idx_legacy_score ON images(quality_score);
            CREATE INDEX IF NOT EXISTS idx_legacy_phash ON images(phash);
        """)
        self._conn.commit()

    def _migrate(self):
        row = self._conn.execute(
            "SELECT value FROM schema_meta WHERE key='version'"
        ).fetchone()
        current = int(row["value"]) if row else 1
        if current < self.SCHEMA_VERSION:
            self._conn.execute(
                "INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('version', ?)",
                (str(self.SCHEMA_VERSION),),
            )
            self._conn.commit()

    # ------------------------------------------------------------------
    # Board CRUD
    # ------------------------------------------------------------------

    def save_board(self, board: Board) -> None:
        self._conn.execute("""
            INSERT OR REPLACE INTO boards
                (id, name, setting_text, visual_goal_summary, style_profile,
                 global_missing_needs, next_search_suggestions, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            board.id,
            board.name,
            board.setting_text,
            board.visual_goal_summary,
            board.style_profile.model_dump_json(),
            _json_dumps(board.global_missing_needs),
            _json_dumps(board.next_search_suggestions),
            board.created_at,
            datetime.now().isoformat(),
        ))
        # Save tracks
        for track in board.reference_tracks:
            self.save_track(track, board.id)
        # Save sections
        for section in board.sections:
            self.save_section(board.id, section)
        self._conn.commit()

    def get_board(self, board_id: str) -> Board | None:
        row = self._conn.execute(
            "SELECT * FROM boards WHERE id = ?", (board_id,)
        ).fetchone()
        if not row:
            return None
        tracks = self.get_tracks(board_id)
        images = self.get_board_images(board_id)
        sections = self.get_sections(board_id)
        return Board(
            id=row["id"],
            name=row["name"],
            setting_text=row["setting_text"],
            visual_goal_summary=row["visual_goal_summary"],
            style_profile=StyleProfile.model_validate_json(row["style_profile"]),
            reference_tracks=tracks,
            images=images,
            sections=sections,
            global_missing_needs=_json_loads_list(row["global_missing_needs"]),
            next_search_suggestions=_json_loads_list(row["next_search_suggestions"]),
            core_references=[],  # Computed dynamically
            anti_references=[],  # Computed dynamically
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def list_boards(self) -> list[dict]:
        rows = self._conn.execute("""
            SELECT b.*,
                   COUNT(DISTINCT bi.id) as image_count,
                   COUNT(DISTINCT rt.id) as track_count
            FROM boards b
            LEFT JOIN board_images bi ON b.id = bi.board_id
            LEFT JOIN reference_tracks rt ON b.id = rt.board_id
            GROUP BY b.id
            ORDER BY b.updated_at DESC
        """).fetchall()
        return [dict(r) for r in rows]

    def delete_board(self, board_id: str) -> None:
        self._conn.execute("DELETE FROM boards WHERE id = ?", (board_id,))
        self._conn.commit()

    # ------------------------------------------------------------------
    # Reference Track CRUD
    # ------------------------------------------------------------------

    def save_track(self, track: ReferenceTrack, board_id: str) -> None:
        self._conn.execute("""
            INSERT OR REPLACE INTO reference_tracks
                (id, board_id, name, description, source_type, target_categories,
                 search_queries, negative_queries, expected_visual_features, relation_to_setting)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            track.id,
            board_id,
            track.name,
            track.description,
            track.source_type,
            _json_dumps(track.target_categories),
            _json_dumps(track.search_queries),
            _json_dumps(track.negative_queries),
            _json_dumps(track.expected_visual_features),
            track.relation_to_setting,
        ))
        self._conn.commit()

    def get_tracks(self, board_id: str) -> list[ReferenceTrack]:
        rows = self._conn.execute(
            "SELECT * FROM reference_tracks WHERE board_id = ?", (board_id,)
        ).fetchall()
        return [
            ReferenceTrack(
                id=r["id"],
                board_id=board_id,
                name=r["name"],
                description=r["description"],
                source_type=r["source_type"],
                target_categories=_json_loads_list(r["target_categories"]),
                search_queries=_json_loads_list(r["search_queries"]),
                negative_queries=_json_loads_list(r["negative_queries"]),
                expected_visual_features=_json_loads_list(r["expected_visual_features"]),
                relation_to_setting=r["relation_to_setting"],
            )
            for r in rows
        ]

    def delete_track(self, track_id: str) -> None:
        self._conn.execute("DELETE FROM reference_tracks WHERE id = ?", (track_id,))
        self._conn.commit()

    # ------------------------------------------------------------------
    # Board Image CRUD
    # ------------------------------------------------------------------

    def add_board_image(self, board_id: str, img: BoardImage) -> None:
        domain = img.source_domain or self._extract_domain(img.source_url)
        img.board_id = board_id
        if not img.source_quality_score or img.source_quality_score == 0.45:
            img.source_quality_score = get_source_quality(domain)

        self._conn.execute("""
            INSERT OR REPLACE INTO board_images
                (id, board_id, track_id, local_path, thumb_path,
                 source_url, page_url, source_domain, source_query,
                 width, height, file_size, sha256, phash, status,
                 categories, visual_metrics, curation_scores, analysis,
                 source_quality_score, final_score, duplicate_penalty,
                 filename, description, tags, style, color_palette,
                 mood, composition, quality_score, use_cases, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            img.id, board_id, img.track_id or None, img.local_path, img.thumb_path,
            img.source_url, img.page_url, domain, img.source_query,
            img.width, img.height, img.file_size, img.sha256, img.phash, img.status,
            _json_dumps([c.model_dump() for c in img.categories]),
            img.visual_metrics.model_dump_json(),
            img.curation_scores.model_dump_json(),
            img.analysis.model_dump_json(),
            img.source_quality_score, img.final_score, img.duplicate_penalty,
            img.filename, img.description,
            _json_dumps(img.tags), img.style,
            _json_dumps(img.color_palette),
            img.mood, img.composition, img.quality_score,
            _json_dumps(img.use_cases), img.created_at,
        ))
        self._conn.commit()

    def update_image_status(self, image_id: str, status: str) -> None:
        self._conn.execute(
            "UPDATE board_images SET status = ? WHERE id = ?",
            (status, image_id),
        )
        self._conn.commit()

    def update_image_scores(self, image_id: str, final_score: float,
                            duplicate_penalty: float, status: str) -> None:
        self._conn.execute("""
            UPDATE board_images
            SET final_score = ?, duplicate_penalty = ?, status = ?
            WHERE id = ?
        """, (final_score, duplicate_penalty, status, image_id))
        self._conn.commit()

    def update_image_analysis(self, image_id: str, analysis: ImageAnalysis,
                              categories: list[ImageCategoryScore],
                              curation: CurationScores,
                              metrics: VisualMetrics) -> None:
        self._conn.execute("""
            UPDATE board_images
            SET analysis = ?, categories = ?, curation_scores = ?, visual_metrics = ?,
                status = CASE
                    WHEN ? = 'reject' THEN 'rejected'
                    ELSE status
                END
            WHERE id = ?
        """, (
            analysis.model_dump_json(),
            _json_dumps([c.model_dump() for c in categories]),
            curation.model_dump_json(),
            metrics.model_dump_json(),
            analysis.final_recommendation,
            image_id,
        ))
        self._conn.commit()

    def get_board_images(self, board_id: str, status: str | None = None) -> list[BoardImage]:
        query = "SELECT * FROM board_images WHERE board_id = ?"
        params: list = [board_id]
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY final_score DESC"

        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_board_image(r) for r in rows]

    def get_image(self, image_id: str) -> BoardImage | None:
        row = self._conn.execute(
            "SELECT * FROM board_images WHERE id = ?", (image_id,)
        ).fetchone()
        return self._row_to_board_image(row) if row else None

    def get_images_by_track(self, track_id: str) -> list[BoardImage]:
        rows = self._conn.execute(
            "SELECT * FROM board_images WHERE track_id = ? ORDER BY final_score DESC",
            (track_id,),
        ).fetchall()
        return [self._row_to_board_image(r) for r in rows]

    def get_images_by_status(self, board_id: str, statuses: list[str]) -> list[BoardImage]:
        placeholders = ",".join("?" for _ in statuses)
        rows = self._conn.execute(f"""
            SELECT * FROM board_images
            WHERE board_id = ? AND status IN ({placeholders})
            ORDER BY final_score DESC
        """, [board_id] + statuses).fetchall()
        return [self._row_to_board_image(r) for r in rows]

    def find_duplicate_by_sha256(self, board_id: str, sha256: str) -> BoardImage | None:
        row = self._conn.execute(
            "SELECT * FROM board_images WHERE board_id = ? AND sha256 = ? AND status != 'duplicate' LIMIT 1",
            (board_id, sha256),
        ).fetchone()
        return self._row_to_board_image(row) if row else None

    def find_similar_by_phash(self, board_id: str, phash: str,
                               threshold: int = 10) -> list[BoardImage]:
        rows = self._conn.execute(
            "SELECT * FROM board_images WHERE board_id = ? AND status != 'duplicate'",
            (board_id,),
        ).fetchall()
        results = []
        for r in rows:
            existing_hash = r["phash"]
            if not existing_hash:
                continue
            hamming = bin(int(existing_hash, 16) ^ int(phash, 16)).count("1")
            if hamming <= threshold:
                results.append(self._row_to_board_image(r))
        return results

    def count_images_by_status(self, board_id: str) -> dict[str, int]:
        rows = self._conn.execute("""
            SELECT status, COUNT(*) as cnt
            FROM board_images
            WHERE board_id = ?
            GROUP BY status
        """, (board_id,)).fetchall()
        return {r["status"]: r["cnt"] for r in rows}

    # ------------------------------------------------------------------
    # Board Section CRUD
    # ------------------------------------------------------------------

    def save_section(self, board_id: str, section: BoardSection) -> None:
        self._conn.execute("""
            INSERT OR REPLACE INTO board_sections
                (board_id, section_id, section_name, summary, design_takeaways,
                 key_images, supporting_images, anti_references, missing_needs)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            board_id, section.section_id, section.section_name, section.summary,
            _json_dumps(section.design_takeaways),
            _json_dumps([r.model_dump() for r in section.key_images]),
            _json_dumps([r.model_dump() for r in section.supporting_images]),
            _json_dumps([r.model_dump() for r in section.anti_references]),
            _json_dumps(section.missing_needs),
        ))
        self._conn.commit()

    def get_sections(self, board_id: str) -> list[BoardSection]:
        rows = self._conn.execute(
            "SELECT * FROM board_sections WHERE board_id = ?", (board_id,)
        ).fetchall()
        return [
            BoardSection(
                section_id=r["section_id"],
                section_name=r["section_name"],
                summary=r["summary"],
                design_takeaways=_json_loads_list(r["design_takeaways"]),
                key_images=[KeyImageRef(**d) for d in _json_loads_list(r["key_images"])],
                supporting_images=[KeyImageRef(**d) for d in _json_loads_list(r["supporting_images"])],
                anti_references=[KeyImageRef(**d) for d in _json_loads_list(r["anti_references"])],
                missing_needs=_json_loads_list(r["missing_needs"]),
            )
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Legacy Collection API (kept for backward compat)
    # ------------------------------------------------------------------

    def create_collection(self, name: str, description: str = "") -> int:
        cur = self._conn.execute(
            "INSERT OR IGNORE INTO collections (name, description) VALUES (?, ?)",
            (name, description),
        )
        self._conn.commit()
        row = self._conn.execute("SELECT id FROM collections WHERE name = ?", (name,)).fetchone()
        return row["id"]

    def add_image(self, collection_id: int, item: dict) -> int:
        tags = item.get("tags", "")
        if isinstance(tags, list):
            tags = ",".join(tags)
        palette = item.get("color_palette", "")
        if isinstance(palette, list):
            palette = ",".join(palette)
        use_cases = item.get("use_cases", "")
        if isinstance(use_cases, list):
            use_cases = ",".join(use_cases)
        cur = self._conn.execute("""
            INSERT INTO images (
                collection_id, filename, original_url, source, local_path,
                thumbnail_path, width, height, file_size, phash,
                description, tags, style, color_palette, mood, composition,
                quality_score, use_cases, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            collection_id, item.get("filename", ""),
            item.get("original_url", item.get("image_url", "")),
            item.get("source", ""), item.get("local_path", ""),
            item.get("thumbnail_path", ""), item.get("width", 0),
            item.get("height", 0), item.get("file_size", 0),
            item.get("phash", ""), item.get("description", ""),
            tags, item.get("style", ""), palette,
            item.get("mood", ""), item.get("composition", ""),
            item.get("quality_score", 0), use_cases,
            item.get("status", "active"),
        ))
        self._conn.commit()
        return cur.lastrowid

    def get_images_by_collection(self, collection_name: str,
                                  tags: list[str] | None = None,
                                  min_score: float | None = None) -> list[dict]:
        query = """
            SELECT i.* FROM images i
            JOIN collections c ON i.collection_id = c.id
            WHERE c.name = ? AND i.status = 'active'
        """
        params: list = [collection_name]
        if tags:
            conditions = " AND ".join(["i.tags LIKE ?" for _ in tags])
            query += f" AND ({conditions})"
            params.extend([f"%{t}%" for t in tags])
        if min_score is not None:
            query += " AND i.quality_score >= ?"
            params.append(min_score)
        query += " ORDER BY i.quality_score DESC"
        rows = self._conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def get_all_tags(self, collection_name: str) -> list[str]:
        rows = self._conn.execute("""
            SELECT i.tags FROM images i
            JOIN collections c ON i.collection_id = c.id
            WHERE c.name = ? AND i.tags != ''
        """, (collection_name,)).fetchall()
        all_tags: set[str] = set()
        for row in rows:
            for tag in row["tags"].split(","):
                tag = tag.strip()
                if tag:
                    all_tags.add(tag)
        return sorted(all_tags)

    def get_collections(self) -> list[dict]:
        rows = self._conn.execute("""
            SELECT c.*, COUNT(i.id) as image_count
            FROM collections c
            LEFT JOIN images i ON c.id = i.collection_id AND i.status = 'active'
            GROUP BY c.id
            ORDER BY c.updated_at DESC
        """).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _row_to_board_image(self, row: sqlite3.Row) -> BoardImage:
        if row is None:
            raise ValueError("Row is None")
        cats_raw = _json_loads_list(row["categories"])
        categories = [ImageCategoryScore(**c) for c in cats_raw]
        return BoardImage(
            id=row["id"],
            board_id=row["board_id"],
            track_id=row["track_id"] or "",
            local_path=row["local_path"],
            thumb_path=row["thumb_path"] or "",
            source_url=row["source_url"] or "",
            page_url=row["page_url"] or "",
            source_domain=row["source_domain"] or "",
            source_query=row["source_query"] or "",
            width=row["width"],
            height=row["height"],
            file_size=row["file_size"],
            sha256=row["sha256"] or "",
            phash=row["phash"] or "",
            status=row["status"],
            categories=categories,
            visual_metrics=VisualMetrics.model_validate_json(row["visual_metrics"]),
            curation_scores=CurationScores.model_validate_json(row["curation_scores"]),
            analysis=ImageAnalysis.model_validate_json(row["analysis"]),
            source_quality_score=row["source_quality_score"],
            final_score=row["final_score"],
            duplicate_penalty=row["duplicate_penalty"],
            filename=row["filename"] or "",
            description=row["description"] or "",
            tags=_json_loads_list(row["tags"]),
            style=row["style"] or "",
            color_palette=_json_loads_list(row["color_palette"]),
            mood=row["mood"] or "",
            composition=row["composition"] or "",
            quality_score=row["quality_score"],
            use_cases=_json_loads_list(row["use_cases"]),
            created_at=row["created_at"],
        )

    @staticmethod
    def _extract_domain(url: str) -> str:
        if not url:
            return ""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            return parsed.netloc.lower()
        except Exception:
            return ""

    def close(self):
        self._conn.close()
