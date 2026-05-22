"""Local HTTP API server for the Canvas Viewer.

Provides REST endpoints for board data access, user ordering,
CLI-equivalent operations (derive-centers, analyze, rank, compose),
and serves the canvas.html viewer.
VLM config is persisted to data/vlm_config.json.
"""

import json
import sys
import threading
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

from config import BOARDS_DIR, DB_PATH, DEFAULT_API_BASE, VLM_CONFIG_PATH, BASE_DIR

# Module-level config for VLM calls
_vlm_model = ""
_vlm_api_key = ""
_vlm_api_base = DEFAULT_API_BASE

# Static files root (gallery/ directory contains canvas.html)
_STATIC_DIR = BASE_DIR / "gallery"


def load_vlm_config() -> dict:
    """Load VLM config from file, falling back to defaults."""
    defaults = {"api_base": DEFAULT_API_BASE, "model": "", "api_key": ""}
    if VLM_CONFIG_PATH.exists():
        try:
            data = json.loads(VLM_CONFIG_PATH.read_text(encoding="utf-8"))
            return {**defaults, **data}
        except (json.JSONDecodeError, OSError):
            pass
    return defaults


def save_vlm_config(model: str = None, api_key: str = None, api_base: str = None):
    """Save VLM config to file, merging with existing values."""
    current = load_vlm_config()
    if model is not None:
        current["model"] = model
    if api_key is not None:
        current["api_key"] = api_key
    if api_base is not None:
        current["api_base"] = api_base
    VLM_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    VLM_CONFIG_PATH.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")


def apply_vlm_config(cfg: dict):
    """Apply a config dict to module-level globals."""
    global _vlm_model, _vlm_api_key, _vlm_api_base
    _vlm_model = cfg.get("model", "")
    _vlm_api_key = cfg.get("api_key", "")
    _vlm_api_base = cfg.get("api_base", DEFAULT_API_BASE)


# ---------------------------------------------------------------------------
# Background workers
# ---------------------------------------------------------------------------

def _run_derive_centers(board_id):
    """Background: derive center values."""
    from analyze.setting_parser import derive_center_values
    from store.database import ImageDatabase
    db = ImageDatabase()
    board = db.get_board(board_id)
    if not board or not board.setting_text:
        db.close()
        return {"error": "Board not found or no setting text"}
    cv = derive_center_values(board.setting_text, _vlm_api_base, _vlm_model, _vlm_api_key)
    board.center_values = cv
    db.save_board(board)
    if board.base_dir:
        board_json = db.export_board_json(board_id)
        if board_json:
            Path(board.base_dir).joinpath("_board.json").write_text(board_json, encoding="utf-8")
    db.close()
    return {"status": "ok", "centers_count": len(cv.centers), "source": cv.source}


def _run_feedback_centers(board_id):
    """Background: derive centers from user feedback."""
    from analyze.setting_parser import derive_centers_from_feedback, merge_center_values
    from store.database import ImageDatabase
    db = ImageDatabase()
    board = db.get_board(board_id)
    if not board:
        db.close()
        return {"error": "Board not found"}
    sections = db.get_sections(board_id)
    images = db.get_board_images(board_id)
    img_map = {img.id: img for img in images}
    ordered_images = []
    for s in sections:
        order = s.user_order or []
        for rank, img_id in enumerate(order):
            if img_id in img_map:
                weight = 1.0 / (1.0 + rank * 0.5)
                ordered_images.append((img_map[img_id], weight))
    if not ordered_images:
        db.close()
        return {"error": "No user orders found. Reorder images in sections first."}
    fb_cv = derive_centers_from_feedback(board.setting_text, ordered_images, _vlm_api_base, _vlm_model, _vlm_api_key)
    old_cv = board.center_values
    if old_cv and old_cv.centers:
        merged = merge_center_values(old_cv, fb_cv, feedback_weight=0.6)
    else:
        merged = fb_cv
    board.center_values = merged
    db.save_board(board)
    if board.base_dir:
        board_json = db.export_board_json(board_id)
        if board_json:
            Path(board.base_dir).joinpath("_board.json").write_text(board_json, encoding="utf-8")
    db.close()
    return {"status": "ok", "centers_count": len(merged.centers), "source": merged.source}


def _run_analyze(board_id):
    """Background: analyze all board images."""
    from analyze.board_analyzer import analyze_board_images
    analyzed = analyze_board_images(board_id, _vlm_api_base, _vlm_model, _vlm_api_key, status_filter=None)
    return {"status": "ok", "analyzed": len(analyzed), "model": _vlm_model}


def _run_rank(board_id):
    """Background: rank and assign statuses."""
    from analyze.board_ranker import rank_board_images
    result = rank_board_images(board_id)
    return result


def _run_compose(board_id):
    """Background: compose board into sections."""
    from analyze.board_composer import compose_board
    result = compose_board(board_id, _vlm_api_base, _vlm_model if _vlm_model else "", _vlm_api_key)
    return result


# ---------------------------------------------------------------------------
# HTTP Handler
# ---------------------------------------------------------------------------

class BoardAPIHandler(BaseHTTPRequestHandler):
    """REST API handler for board operations + static file serving."""

    def log_message(self, format, *args):
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
            pass

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

    def _run_async(self, board_id, fn):
        """Run a long operation in background, return immediate ack."""
        def worker():
            try:
                fn(board_id)
            except Exception as e:
                print(f"[{fn.__name__}] error: {e}", file=sys.stderr)
        t = threading.Thread(target=worker, daemon=True)
        t.start()
        self._send_json({"status": "started", "board_id": board_id, "action": fn.__name__})

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

        # ── API endpoints ──
        if path == "/api/health":
            self._send_json({"status": "ok"})

        elif path == "/api/vlm-config":
            key_display = ""
            if _vlm_api_key:
                key_display = _vlm_api_key[:8] + "..." + _vlm_api_key[-4:] if len(_vlm_api_key) > 12 else "***"
            self._send_json({
                "model": _vlm_model,
                "api_base": _vlm_api_base,
                "api_key_set": bool(_vlm_api_key),
                "api_key_display": key_display,
            })

        elif path == "/api/boards":
            db = self._get_db()
            boards = db.list_boards()
            db.close()
            self._send_json(boards)

        elif path.startswith("/api/boards/"):
            parts = path.split("/")
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
                db = self._get_db()
                board = db.get_board(board_id)
                db.close()
                if not board:
                    self._send_json({"error": "Board not found"}, 404)
                    return
                data = board.model_dump()
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
            # ── Static file serving (canvas.html etc.) ──
            file_path = path.lstrip("/") or "canvas.html"
            full_path = _STATIC_DIR / file_path
            if full_path.exists() and full_path.is_file():
                mime_map = {
                    ".html": "text/html; charset=utf-8",
                    ".css": "text/css; charset=utf-8",
                    ".js": "application/javascript; charset=utf-8",
                    ".json": "application/json",
                    ".png": "image/png",
                    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                    ".svg": "image/svg+xml",
                    ".ico": "image/x-icon",
                }
                ct = mime_map.get(full_path.suffix.lower(), "application/octet-stream")
                self._send_file(full_path, ct)
            else:
                self._send_json({"error": f"Not found: {path}"}, 404)

    def do_POST(self):
        path = unquote(urlparse(self.path).path.rstrip("/"))

        if path == "/api/vlm-config":
            # Update VLM config in memory AND persist to file
            global _vlm_model, _vlm_api_key, _vlm_api_base
            body = self._read_body()
            model = body.get("model")
            api_key = body.get("api_key")
            api_base = body.get("api_base")
            if model is not None:
                _vlm_model = model
            if api_key is not None:
                _vlm_api_key = api_key
            if api_base is not None:
                _vlm_api_base = api_base
            save_vlm_config(model, api_key, api_base)
            print(f"VLM config updated: model={_vlm_model}, base={_vlm_api_base}", file=sys.stderr)
            self._send_json({"status": "ok", "model": _vlm_model, "api_base": _vlm_api_base})
            return

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
                    sections = db.get_sections(board_id)
                    board.sections = sections
                    comp_path.write_text(
                        json.dumps({"board_id": board_id, "sections": [s.model_dump() for s in sections]}, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
            db.close()
            self._send_json({"status": "ok"})

        elif sub == "export-order":
            db = self._get_db()
            sections = db.get_sections(board_id)
            db.close()
            orders = {s.section_id: s.user_order for s in sections if s.user_order}
            self._send_json({"board_id": board_id, "sections": orders})

        elif sub == "update-centers":
            body = self._read_body()
            db = self._get_db()
            board = db.get_board(board_id)
            if not board:
                db.close()
                self._send_json({"error": "Board not found"}, 404)
                return
            from models.schemas import BoardCenterValues
            board.center_values = BoardCenterValues.model_validate(body)
            db.save_board(board)
            db.close()
            self._send_json({"status": "ok", "centers": len(board.center_values.centers)})

        elif sub == "recompute-scores":
            from analyze.board_ranker import compute_dimension_distance_score, assign_status_v2
            db = self._get_db()
            board = db.get_board(board_id)
            if not board:
                db.close()
                self._send_json({"error": "Board not found"}, 404)
                return
            images = db.get_board_images(board_id)
            for img in images:
                if img.status == "duplicate":
                    continue
                score = compute_dimension_distance_score(img, board.center_values)
                status = assign_status_v2(img, score)
                img.dimension_distance_score = score
                img.final_score = score
                img.status = status
                db.update_image_scores(img.id, score, img.duplicate_penalty, status)
                db.update_image_dimension_score(img.id, score)
            db.close()
            self._send_json({"status": "ok", "images_updated": len(images)})

        elif sub == "derive-centers":
            self._run_async(board_id, _run_derive_centers)

        elif sub == "feedback-centers":
            self._run_async(board_id, _run_feedback_centers)

        elif sub == "analyze":
            self._run_async(board_id, _run_analyze)

        elif sub == "rank":
            self._run_async(board_id, _run_rank)

        elif sub == "compose":
            self._run_async(board_id, _run_compose)

        else:
            self._send_json({"error": f"Unknown endpoint: POST {path}"}, 404)


# ---------------------------------------------------------------------------
# Server entry point
# ---------------------------------------------------------------------------

def start_server(port: int = 8765, open_browser: bool = True):
    """Start the API server. Loads VLM config from file."""
    cfg = load_vlm_config()
    apply_vlm_config(cfg)

    server = HTTPServer(("127.0.0.1", port), BoardAPIHandler)
    url = f"http://localhost:{port}"
    print(f"Art Ref Canvas running at {url}", file=sys.stderr)
    if _vlm_model:
        print(f"VLM model: {_vlm_model}", file=sys.stderr)
    else:
        print(f"VLM not configured — set via {VLM_CONFIG_PATH} or the web UI", file=sys.stderr)

    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.", file=sys.stderr)
        server.server_close()
