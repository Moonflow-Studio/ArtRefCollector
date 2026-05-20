"""Local HTTP API server for the Canvas Viewer.

Provides REST endpoints for board data access and user ordering.
The viewer auto-detects this server and uses it for seamless write-back.
Falls back to JSON export if server is not running.
"""

import json
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

from config import BOARDS_DIR, DB_PATH


class BoardAPIHandler(BaseHTTPRequestHandler):
    """REST API handler for board operations."""

    def log_message(self, format, *args):
        # Quieter logging: only show errors
        if args and args[0].startswith("200"):
            return
        super().log_message(format, *args)

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path, content_type: str = "application/json"):
        if not path.exists():
            self._send_json({"error": f"Not found: {path}"}, 404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        try:
            self.wfile.write(data)
        except ConnectionError:
            pass  # Client disconnected, ignore

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    def _get_db(self):
        from store.database import ImageDatabase
        return ImageDatabase()

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = unquote(urlparse(self.path).path.rstrip("/"))
        query = parse_qs(urlparse(self.path).query)

        if path == "/api/health":
            self._send_json({"status": "ok"})

        elif path == "/api/boards":
            db = self._get_db()
            boards = db.list_boards()
            db.close()
            self._send_json(boards)

        elif path.startswith("/api/boards/"):
            parts = path.split("/")
            # /api/boards/<board_id>
            # /api/boards/<board_id>/sections
            # /api/boards/<board_id>/images
            board_id = parts[3] if len(parts) > 3 else ""

            if not board_id:
                self._send_json({"error": "Board ID required"}, 400)
                return

            sub = parts[4] if len(parts) > 4 else ""

            if sub == "sections":
                db = self._get_db()
                sections = db.get_sections(board_id)
                db.close()
                self._send_json([s.model_dump() for s in sections])

            elif sub == "images":
                db = self._get_db()
                status = query.get("status", [None])[0]
                images = db.get_board_images(board_id, status=status)
                db.close()
                self._send_json([img.model_dump() for img in images])

            elif sub == "composition":
                db = self._get_db()
                board = db.get_board(board_id)
                db.close()
                if not board:
                    self._send_json({"error": "Board not found"}, 404)
                    return
                comp_path = Path(board.base_dir) / "board_composition.json" if board.base_dir else None
                if comp_path and comp_path.exists():
                    self._send_file(comp_path)
                else:
                    self._send_json({"error": "No composition found"}, 404)

            elif sub == "image" and len(parts) > 5:
                # /api/boards/<id>/image/<filename> — serve image file
                filename = parts[5]
                db = self._get_db()
                board = db.get_board(board_id)
                db.close()
                if not board or not board.base_dir:
                    self._send_json({"error": "Board not found"}, 404)
                    return
                img_path = Path(board.base_dir) / "images" / filename
                ext = img_path.suffix.lower()
                mime = {
                    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                    ".png": "image/png", ".webp": "image/webp",
                    ".gif": "image/gif",
                }.get(ext, "application/octet-stream")
                self._send_file(img_path, mime)

            elif sub == "thumb" and len(parts) > 5:
                # /api/boards/<id>/thumb/<filename>
                filename = parts[5]
                db = self._get_db()
                board = db.get_board(board_id)
                db.close()
                if not board or not board.base_dir:
                    self._send_json({"error": "Board not found"}, 404)
                    return
                thumb_path = Path(board.base_dir) / "thumbnails" / filename
                self._send_file(thumb_path, "image/jpeg")

            else:
                # Return full board data
                db = self._get_db()
                board = db.get_board(board_id)
                db.close()
                if not board:
                    self._send_json({"error": "Board not found"}, 404)
                    return
                data = board.model_dump()
                # Convert image paths to API URLs for the viewer
                base_url = f"/api/boards/{board_id}"
                for img in data.get("images", []):
                    lp = img.get("local_path", "")
                    if lp:
                        fname = Path(lp).name
                        img["api_url"] = f"{base_url}/image/{fname}"
                    tp = img.get("thumb_path", "")
                    if tp:
                        fname = Path(tp).name
                        img["api_thumb_url"] = f"{base_url}/thumb/{fname}"
                self._send_json(data)

        else:
            self._send_json({"error": f"Unknown endpoint: {path}"}, 404)

    def do_POST(self):
        path = unquote(urlparse(self.path).path.rstrip("/"))

        if not path.startswith("/api/boards/"):
            self._send_json({"error": "Unknown endpoint"}, 404)
            return

        parts = path.split("/")
        board_id = parts[3] if len(parts) > 3 else ""
        sub = parts[4] if len(parts) > 4 else ""

        if not board_id:
            self._send_json({"error": "Board ID required"}, 400)
            return

        if sub == "sections" and len(parts) > 5:
            # POST /api/boards/<id>/sections/<section_id>/reorder
            section_id = parts[5]
            action = parts[6] if len(parts) > 6 else ""
            if action == "reorder":
                body = self._read_body()
                user_order = body.get("order", [])
                if not isinstance(user_order, list):
                    self._send_json({"error": "order must be a list"}, 400)
                    return
                db = self._get_db()
                sections = db.get_sections(board_id)
                found = False
                for section in sections:
                    if section.section_id == section_id:
                        section.user_order = user_order
                        db.save_section(board_id, section)
                        found = True
                        break
                if not found:
                    db.close()
                    self._send_json({"error": f"Section {section_id} not found"}, 404)
                    return
                # Update _board.json
                board = db.get_board(board_id)
                if board and board.base_dir:
                    board_json = db.export_board_json(board_id)
                    if board_json:
                        Path(board.base_dir).joinpath("_board.json").write_text(
                            board_json, encoding="utf-8"
                        )
                db.close()
                self._send_json({"status": "ok", "section": section_id, "user_order": user_order})
            else:
                self._send_json({"error": f"Unknown action: {action}"}, 400)

        elif sub == "refresh":
            # POST /api/boards/<id>/refresh — regenerate _board.json
            db = self._get_db()
            board_json = db.export_board_json(board_id)
            if not board_json:
                db.close()
                self._send_json({"error": "Board not found"}, 404)
                return
            board = db.get_board(board_id)
            if board and board.base_dir:
                Path(board.base_dir).joinpath("_board.json").write_text(
                    board_json, encoding="utf-8"
                )
                comp_path = Path(board.base_dir) / "board_composition.json"
                if comp_path.exists():
                    # Also refresh composition file
                    sections = db.get_sections(board_id)
                    board.sections = sections
                    comp_path.write_text(
                        json.dumps({"board_id": board_id, "sections": [s.model_dump() for s in sections]}, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
            db.close()
            self._send_json({"status": "ok"})

        elif sub == "export-order":
            # POST /api/boards/<id>/export-order — return user_order JSON for download
            db = self._get_db()
            sections = db.get_sections(board_id)
            db.close()
            orders = {s.section_id: s.user_order for s in sections if s.user_order}
            self._send_json({"board_id": board_id, "sections": orders})

        else:
            self._send_json({"error": f"Unknown endpoint: POST {path}"}, 404)


def start_server(port: int = 8765):
    server = HTTPServer(("127.0.0.1", port), BoardAPIHandler)
    print(f"Board API server running at http://localhost:{port}", file=sys.stderr)
    print(f"Endpoints:", file=sys.stderr)
    print(f"  GET  /api/health", file=sys.stderr)
    print(f"  GET  /api/boards", file=sys.stderr)
    print(f"  GET  /api/boards/<id>", file=sys.stderr)
    print(f"  GET  /api/boards/<id>/sections", file=sys.stderr)
    print(f"  GET  /api/boards/<id>/images", file=sys.stderr)
    print(f"  GET  /api/boards/<id>/composition", file=sys.stderr)
    print(f"  GET  /api/boards/<id>/image/<filename>", file=sys.stderr)
    print(f"  POST /api/boards/<id>/sections/<sid>/reorder", file=sys.stderr)
    print(f"  POST /api/boards/<id>/refresh", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.", file=sys.stderr)
        server.server_close()
