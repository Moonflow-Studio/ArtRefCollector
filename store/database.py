import json
import sqlite3
from datetime import datetime
from pathlib import Path

from config import DB_PATH


class ImageDatabase:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or str(DB_PATH)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self):
        self._conn.executescript("""
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
            CREATE INDEX IF NOT EXISTS idx_images_score ON images(quality_score);
            CREATE INDEX IF NOT EXISTS idx_images_phash ON images(phash);
        """)
        self._conn.commit()

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
            collection_id,
            item.get("filename", ""),
            item.get("original_url", item.get("image_url", "")),
            item.get("source", ""),
            item.get("local_path", ""),
            item.get("thumbnail_path", ""),
            item.get("width", 0),
            item.get("height", 0),
            item.get("file_size", 0),
            item.get("phash", ""),
            item.get("description", ""),
            tags,
            item.get("style", ""),
            palette,
            item.get("mood", ""),
            item.get("composition", ""),
            item.get("quality_score", 0),
            use_cases,
            item.get("status", "active"),
        ))
        self._conn.commit()
        return cur.lastrowid

    def get_images_by_collection(
        self,
        collection_name: str,
        tags: list[str] | None = None,
        min_score: float | None = None,
    ) -> list[dict]:
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

    def close(self):
        self._conn.close()
