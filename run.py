import argparse
import json
import sys
import uuid
from pathlib import Path

from config import DATA_DIR, SESSIONS_DIR, BOARDS_DIR


def ensure_dirs():
    for d in [DATA_DIR / "images", DATA_DIR / "thumbnails", SESSIONS_DIR,
              DATA_DIR / "faiss_index", DATA_DIR / "lancedb",
              DATA_DIR / "galleries", DATA_DIR / "metrics", BOARDS_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def _sanitize_board_id(name: str) -> str:
    """Create a filesystem-safe board ID from a name."""
    import re
    # Remove/replace characters unsafe for directory names
    cleaned = name.strip()
    cleaned = re.sub(r'[<>:"/\\|?*]', '_', cleaned)
    cleaned = re.sub(r'\s+', '_', cleaned)
    cleaned = re.sub(r'_+', '_', cleaned)
    cleaned = cleaned.strip('_')
    # Limit length
    if len(cleaned) > 80:
        cleaned = cleaned[:80].rstrip('_')
    return cleaned or f"board_{uuid.uuid4().hex[:8]}"


def new_session() -> str:
    sid = uuid.uuid4().hex[:12]
    session_dir = SESSIONS_DIR / sid
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "search_results.json").write_text("[]")
    (session_dir / "downloads.json").write_text("[]")
    return sid


def load_session(sid: str) -> dict:
    session_dir = SESSIONS_DIR / sid
    if not session_dir.exists():
        print(json.dumps({"error": f"Session {sid} not found"}))
        sys.exit(1)
    results = json.loads((session_dir / "search_results.json").read_text())
    downloads = json.loads((session_dir / "downloads.json").read_text())
    return {"id": sid, "dir": str(session_dir), "search_results": results, "downloads": downloads}


def save_session_data(sid: str, filename: str, data):
    path = SESSIONS_DIR / sid / filename
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def _ask_vector_backend(args):
    """Determine vector backend, prompting user if needed."""
    backend = getattr(args, "vector_backend", None)
    if backend:
        return backend
    try:
        choice = input("向量存储后端 [faiss/lancedb] (默认 faiss): ").strip().lower()
        return choice if choice in ("faiss", "lancedb") else "faiss"
    except (EOFError, KeyboardInterrupt):
        return "faiss"


def cmd_search(args):
    from search.search_factory import get_searcher
    ensure_dirs()
    sid = new_session()
    searcher = get_searcher(args.search_backend)
    results = searcher(
        keywords=args.keywords,
        max_results=args.max,
        region=args.region,
        safesearch=args.safesearch,
        size=args.size,
        type_image=args.type if hasattr(args, 'type') else None,
        layout=args.layout,
    )
    save_session_data(sid, "search_results.json", results)
    print(json.dumps({"session_id": sid, "count": len(results), "results": results}, ensure_ascii=False))


def cmd_download(args):
    from download.download_factory import get_downloader
    ensure_dirs()
    session = load_session(args.session)
    output_dir = DATA_DIR / "images" / args.session
    output_dir.mkdir(parents=True, exist_ok=True)
    import asyncio
    downloader = get_downloader(args.download_backend)
    downloaded = asyncio.run(downloader(
        url_list=session["search_results"],
        output_dir=str(output_dir),
        max_concurrent=args.concurrent,
    ))
    save_session_data(args.session, "downloads.json", downloaded)
    print(json.dumps({"session_id": args.session, "downloaded": len(downloaded), "results": downloaded}, ensure_ascii=False))


def cmd_dedup(args):
    ensure_dirs()
    session = load_session(args.session)
    downloads = session["downloads"]
    if not downloads:
        print(json.dumps({"error": "No downloads to deduplicate"}))
        sys.exit(1)

    from dedup.phash_dedup import find_duplicates_phash
    dup_groups = find_duplicates_phash(downloads, hamming_threshold=args.phash_threshold)

    if args.clip and dup_groups:
        from dedup.clip_dedup import find_duplicates_clip
        dup_groups = find_duplicates_clip(downloads, similarity_threshold=args.threshold)

    duplicate_ids = set()
    for group in dup_groups:
        duplicate_ids.update(group[1:])

    kept = [d for d in downloads if d.get("filename", d.get("local_path", "")) not in duplicate_ids]
    save_session_data(args.session, "downloads.json", kept)

    print(json.dumps({
        "session_id": args.session,
        "original_count": len(downloads),
        "duplicates_removed": len(duplicate_ids),
        "remaining": len(kept),
        "duplicate_groups": dup_groups,
    }, ensure_ascii=False))


def cmd_analyze(args):
    ensure_dirs()
    session = load_session(args.session)
    downloads = session["downloads"]
    if not downloads:
        print(json.dumps({"error": "No images to analyze"}))
        sys.exit(1)

    from analyze.vision_tagger import tag_images
    results = tag_images(
        images=downloads,
        api_base=args.api_base,
        model=args.model,
        api_key=args.api_key,
    )
    save_session_data(args.session, "downloads.json", results)
    print(json.dumps({"session_id": args.session, "analyzed": len(results)}, ensure_ascii=False))


def cmd_metrics(args):
    """Compute per-image metrics (pixel + optional VLM) and write JSON config per image."""
    ensure_dirs()
    session = load_session(args.session)
    downloads = session["downloads"]
    if not downloads:
        print(json.dumps({"error": "No images to analyze"}))
        sys.exit(1)

    from analyze.pixel_metrics import compute_all
    from analyze.vlm_metrics import analyze_subjective

    metrics_dir = DATA_DIR / "metrics" / args.session
    metrics_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for i, item in enumerate(downloads):
        if item.get("status") != "success":
            results.append(item)
            continue
        path = item.get("local_path", "")
        if not path or not Path(path).exists():
            results.append(item)
            continue

        filename = Path(path).stem
        metrics_file = metrics_dir / f"{filename}.json"

        # Skip if already computed
        if metrics_file.exists() and not args.force:
            existing = json.loads(metrics_file.read_text(encoding="utf-8"))
            item["metrics_file"] = str(metrics_file)
            results.append(item)
            print(f"  [{i+1}/{len(downloads)}] Skipped (exists): {filename}", file=sys.stderr)
            continue

        # Pixel metrics
        print(f"  [{i+1}/{len(downloads)}] Pixel metrics: {filename}", file=sys.stderr)
        pixel = compute_all(path)

        # VLM metrics (optional)
        subjective = {}
        if args.vlm:
            try:
                print(f"    VLM analysis: {filename}", file=sys.stderr)
                subjective = analyze_subjective(
                    path,
                    api_base=args.api_base,
                    model=args.model,
                    api_key=args.api_key,
                )
            except Exception as e:
                print(f"    VLM failed: {e}", file=sys.stderr)

        # Build per-image config
        img_config = {
            "image_id": filename,
            "filename": Path(path).name,
            "source": item.get("source", ""),
            "original_url": item.get("image_url", ""),
            "tags": item.get("tags", []) if isinstance(item.get("tags"), list) else [t.strip() for t in item.get("tags", "").split(",") if t.strip()],
            "description": item.get("description", ""),
            "visual_metrics": pixel,
            "subjective_metrics": subjective,
        }
        metrics_file.write_text(json.dumps(img_config, ensure_ascii=False, indent=2), encoding="utf-8")
        item["metrics_file"] = str(metrics_file)
        results.append(item)

    save_session_data(args.session, "downloads.json", results)
    total_pixel = sum(1 for r in results if r.get("metrics_file"))
    total_vlm = 0
    for r in results:
        mf = r.get("metrics_file", "")
        if mf and Path(mf).exists():
            try:
                md = json.loads(Path(mf).read_text(encoding="utf-8"))
                if md.get("subjective_metrics"):
                    total_vlm += 1
            except (json.JSONDecodeError, OSError):
                pass
    print(json.dumps({
        "session_id": args.session,
        "metrics_dir": str(metrics_dir),
        "pixel_analyzed": total_pixel,
        "vlm_analyzed": total_vlm,
    }, ensure_ascii=False))


def cmd_store(args):
    ensure_dirs()
    session = load_session(args.session)
    downloads = session["downloads"]

    from store.database import ImageDatabase
    from store.file_manager import organize_files
    from store.vector_store_factory import get_vector_store

    db = ImageDatabase()
    collection_id = db.create_collection(args.topic)
    organized = organize_files(downloads, args.topic)

    # Determine vector backend
    backend = _ask_vector_backend(args)

    embeddings = []
    img_ids = []
    for item in organized:
        img_id = db.add_image(collection_id, item)

        # Compute missing embeddings
        if not item.get("clip_embedding"):
            path = item.get("local_path", "")
            if path and Path(path).exists():
                from store.embedding_utils import encode_image
                emb = encode_image(path)
                if emb is not None:
                    item["clip_embedding"] = emb.tolist()

        if item.get("clip_embedding"):
            embeddings.append(item["clip_embedding"])
            img_ids.append(img_id)

    if embeddings:
        import numpy as np
        vi = get_vector_store(backend)
        for iid, emb in zip(img_ids, embeddings):
            meta = {"collection_id": collection_id, "tags": item.get("tags", "")}
            if hasattr(vi, 'add'):
                vi.add(iid, np.array(emb, dtype="float32"), metadata=meta)
        vi.save()

    print(json.dumps({
        "session_id": args.session,
        "collection": args.topic,
        "stored": len(organized),
        "vector_backend": backend,
    }, ensure_ascii=False))


def cmd_gallery(args):
    """Generate _collection.json config in each topic's image folder."""
    ensure_dirs()
    from store.database import ImageDatabase

    db = ImageDatabase()
    topics = args.topic if isinstance(args.topic, list) else [args.topic]
    results = []

    for topic in topics:
        images = db.get_images_by_collection(topic, tags=args.tags, min_score=args.min_score)
        if not images:
            print(json.dumps({"error": f"No images found for topic '{topic}'"}), file=sys.stderr)
            continue

        topic_dir = DATA_DIR / "images" / topic
        if not topic_dir.exists():
            print(json.dumps({"error": f"Image folder not found: {topic_dir}"}), file=sys.stderr)
            continue

        col_images = []
        for img in images:
            entry = {
                "path": img["filename"],  # bare filename, same folder as _collection.json
                "description": img.get("description", ""),
                "tags": [t.strip() for t in img.get("tags", "").split(",") if t.strip()] if img.get("tags") else [],
                "score": img.get("quality_score", 0),
                "mood": img.get("mood", ""),
                "style": img.get("style", ""),
            }

            # Embed metrics from per-image JSON
            metrics_dir = DATA_DIR / "metrics"
            img_stem = Path(img.get("filename", "")).stem
            for session_dir in metrics_dir.iterdir():
                mf = session_dir / f"{img_stem}.json"
                if mf.exists():
                    try:
                        mdata = json.loads(mf.read_text(encoding="utf-8"))
                        if mdata.get("visual_metrics"):
                            entry["visual_metrics"] = mdata["visual_metrics"]
                        if mdata.get("subjective_metrics"):
                            entry["subjective_metrics"] = mdata["subjective_metrics"]
                        break
                    except (json.JSONDecodeError, KeyError):
                        pass

            col_images.append(entry)

        idx = len(results)
        colors = ["#4a90d9", "#d4a03c", "#3cb878", "#c75d5d", "#7e6db5", "#5db5a3"]
        col_config = {
            "id": topic,
            "name": topic.replace("_", " "),
            "color": colors[idx % len(colors)],
            "layout": {"type": "grid", "columns": 5, "cellSize": 280, "gap": 10, "padding": 20},
            "images": col_images,
        }

        # Write _collection.json into the topic image folder
        config_path = topic_dir / "_collection.json"
        config_path.write_text(json.dumps(col_config, ensure_ascii=False, indent=2), encoding="utf-8")
        with_metrics = sum(1 for img in col_images if img.get("visual_metrics"))
        results.append({"topic": topic, "path": str(config_path), "images": len(col_images), "with_metrics": with_metrics})
        print(json.dumps(results[-1], ensure_ascii=False))

    print(json.dumps({"generated": len(results), "topics": results}, ensure_ascii=False))


def cmd_parse(args):
    """Parse a text setting into structured visual requirements."""
    from analyze.setting_parser import parse_setting
    from store.database import ImageDatabase

    setting_text = args.setting
    if args.file:
        setting_text = Path(args.file).read_text(encoding="utf-8")

    result = parse_setting(
        setting_text=setting_text,
        api_base=args.api_base,
        model=args.model,
        api_key=args.api_key,
    )

    # Sanitize board_id: human-readable, filesystem-safe
    board_name = args.name or setting_text[:30]
    board_id = _sanitize_board_id(board_name)

    from models import Board
    board_dir = BOARDS_DIR / board_id
    board_dir.mkdir(parents=True, exist_ok=True)
    (board_dir / "images").mkdir(exist_ok=True)
    (board_dir / "thumbnails").mkdir(exist_ok=True)

    board = Board(
        id=board_id,
        name=board_name,
        base_dir=str(board_dir.resolve()),
        setting_text=setting_text,
        visual_goal_summary=", ".join(result.style_profile.mood + result.style_profile.color[:3]),
        style_profile=result.style_profile,
    )

    # Save parse result into board folder
    parse_path = board_dir / "parse_result.json"
    parse_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")

    # Save board to DB
    db = ImageDatabase()
    db.save_board(board)
    # Export _board.json (self-contained, relative paths)
    board_json = db.export_board_json(board_id)
    if board_json:
        (board_dir / "_board.json").write_text(board_json, encoding="utf-8")
    db.close()

    output = {
        "board_id": board_id,
        "board_name": board.name,
        "board_dir": str(board_dir),
        "parse_result": result.model_dump(),
        "parse_file": str(parse_path),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))

    if result.clarification_questions:
        print("\n需要澄清的问题:", file=sys.stderr)
        for q in result.clarification_questions:
            print(f"  - {q}", file=sys.stderr)


def cmd_plan(args):
    """Generate Reference Tracks from a board's parsed setting."""
    from analyze.reference_planner import plan_references
    from store.database import ImageDatabase

    db = ImageDatabase()
    board = db.get_board(args.board)
    if not board:
        print(json.dumps({"error": f"Board {args.board} not found"}))
        sys.exit(1)

    # Load parse result if available
    parse_path = Path(board.base_dir) / "parse_result.json"
    from models.schemas import SettingParseResult
    if parse_path.exists():
        parse_result = SettingParseResult.model_validate_json(parse_path.read_text(encoding="utf-8"))
    else:
        # Fallback: create minimal parse result from board
        parse_result = SettingParseResult(
            core_concepts=[board.name],
            style_profile=board.style_profile,
        )

    tracks = plan_references(
        parse_result=parse_result,
        setting_text=board.setting_text,
        api_base=args.api_base,
        model=args.model,
        api_key=args.api_key,
    )

    # Save tracks to board
    board.reference_tracks = tracks
    db.save_board(board)

    # Save tracks file into board folder
    tracks_path = Path(board.base_dir) / "reference_tracks.json"
    tracks_path.write_text(
        json.dumps([t.model_dump() for t in tracks], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Update _board.json
    board_json = db.export_board_json(args.board)
    if board_json:
        (Path(board.base_dir) / "_board.json").write_text(board_json, encoding="utf-8")
    db.close()

    output = {
        "board_id": args.board,
        "track_count": len(tracks),
        "tracks": [t.model_dump() for t in tracks],
        "tracks_file": str(tracks_path),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))

    total_queries = sum(len(t.search_queries) for t in tracks)
    print(f"\n生成 {len(tracks)} 条参考线索，共 {total_queries} 个搜索查询", file=sys.stderr)


def cmd_analyze_board(args):
    """Analyze board images with board-aware VLM analysis."""
    from analyze.board_analyzer import analyze_board_images

    analyzed = analyze_board_images(
        board_id=args.board,
        api_base=args.api_base,
        model=args.model,
        api_key=args.api_key,
        status_filter=args.status or "candidate",
    )

    output = {
        "board_id": args.board,
        "analyzed": len(analyzed),
        "model": args.model,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


def cmd_rank(args):
    """Run dedup + scoring + status assignment for a board."""
    from analyze.board_ranker import rank_board_images

    result = rank_board_images(
        board_id=args.board,
        phash_threshold=args.phash_threshold,
        clip_threshold=args.threshold,
        use_clip=args.clip,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_compose(args):
    """Compose a structured reference board from analyzed images."""
    from analyze.board_composer import compose_board

    result = compose_board(
        board_id=args.board,
        api_base=args.api_base,
        model=args.model if args.model else "",
        api_key=args.api_key,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_reorder(args):
    """Set user-defined image ordering for a board section."""
    from store.database import ImageDatabase

    db = ImageDatabase()
    sections = db.get_sections(args.board)
    order = args.order

    updated = False
    for section in sections:
        if section.section_id == args.section:
            section.user_order = order
            db.save_section(args.board, section)
            updated = True
            break

    if not updated:
        print(json.dumps({"error": f"Section '{args.section}' not found in board '{args.board}'"}))
        db.close()
        sys.exit(1)

    # Update _board.json
    board = db.get_board(args.board)
    if board and board.base_dir:
        board_json = db.export_board_json(args.board)
        if board_json:
            Path(board.base_dir).joinpath("_board.json").write_text(board_json, encoding="utf-8")

    db.close()
    print(json.dumps({
        "board_id": args.board,
        "section": args.section,
        "user_order": order,
    }, ensure_ascii=False))


def cmd_serve(args):
    """Start local API server for the Canvas Viewer."""
    ensure_dirs()
    from serve.board_api import start_server
    start_server(port=args.port)


def cmd_pipeline(args):
    ensure_dirs()
    sid = new_session()
    print(json.dumps({"status": "searching", "session_id": sid}), file=sys.stderr)

    from search.search_factory import get_searcher
    from download.download_factory import get_downloader
    from dedup.phash_dedup import find_duplicates_phash
    from dedup.clip_dedup import find_duplicates_clip
    from store.database import ImageDatabase
    from store.file_manager import organize_files
    from store.vector_store_factory import get_vector_store
    from display.gallery_generator import generate_gallery
    import asyncio

    # Search
    searcher = get_searcher(args.search_backend)
    results = searcher(args.keywords, max_results=args.max, region=args.region)
    save_session_data(sid, "search_results.json", results)
    print(json.dumps({"status": "searched", "count": len(results)}), file=sys.stderr)

    # Download
    output_dir = DATA_DIR / "images" / sid
    output_dir.mkdir(parents=True, exist_ok=True)
    downloader = get_downloader(args.download_backend)
    downloads = asyncio.run(downloader(url_list=results, output_dir=str(output_dir)))
    save_session_data(sid, "downloads.json", downloads)
    print(json.dumps({"status": "downloaded", "count": len(downloads)}), file=sys.stderr)

    # Dedup
    dup_groups = find_duplicates_phash(downloads, hamming_threshold=args.phash_threshold)
    if args.clip and dup_groups:
        dup_groups = find_duplicates_clip(downloads, similarity_threshold=args.threshold)
    dup_ids = set()
    for g in dup_groups:
        dup_ids.update(g[1:])
    downloads = [d for d in downloads if d.get("filename", d.get("local_path", "")) not in dup_ids]
    save_session_data(sid, "downloads.json", downloads)
    print(json.dumps({"status": "deduplicated", "remaining": len(downloads)}), file=sys.stderr)

    # Analyze
    if args.model:
        from analyze.vision_tagger import tag_images
        downloads = tag_images(downloads, api_base=args.api_base, model=args.model)
        save_session_data(sid, "downloads.json", downloads)
        print(json.dumps({"status": "analyzed", "count": len(downloads)}), file=sys.stderr)

    # Store
    backend = _ask_vector_backend(args)
    db = ImageDatabase()
    collection_id = db.create_collection(args.topic)
    organized = organize_files(downloads, args.topic)

    embeddings = []
    img_ids = []
    for item in organized:
        img_id = db.add_image(collection_id, item)

        # Compute missing embeddings
        if not item.get("clip_embedding"):
            path = item.get("local_path", "")
            if path and Path(path).exists():
                from store.embedding_utils import encode_image
                emb = encode_image(path)
                if emb is not None:
                    item["clip_embedding"] = emb.tolist()

        if item.get("clip_embedding"):
            embeddings.append(item["clip_embedding"])
            img_ids.append(img_id)

    if embeddings:
        import numpy as np
        vi = get_vector_store(backend)
        for iid, emb in zip(img_ids, embeddings):
            vi.add(iid, np.array(emb, dtype="float32"))
        vi.save()

    # Gallery
    images = db.get_images_by_collection(args.topic)
    output_path = generate_gallery(images=images, title=args.topic, output_dir=str(DATA_DIR / "galleries"))

    print(json.dumps({
        "session_id": sid,
        "collection": args.topic,
        "searched": len(results),
        "downloaded": len([d for d in downloads if d.get("status") == "success"]),
        "after_dedup": len(downloads),
        "stored": len(organized),
        "vector_backend": backend,
        "gallery_path": str(output_path),
    }, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description="Art Reference Collector")
    sub = parser.add_subparsers(dest="command")

    # search
    p = sub.add_parser("search")
    p.add_argument("keywords")
    p.add_argument("--max", type=int, default=30)
    p.add_argument("--region", default="wt-wt")
    p.add_argument("--safesearch", default="moderate")
    p.add_argument("--size", default=None, choices=["Small", "Medium", "Large", "Wallpaper"])
    p.add_argument("--type", default=None, choices=["photo", "clipart", "transparent", "line"])
    p.add_argument("--layout", default=None, choices=["Square", "Tall", "Wide"])
    p.add_argument("--search-backend", default=None, choices=["auto", "searxng", "duckduckgo"])

    # download
    p = sub.add_parser("download")
    p.add_argument("--session", required=True)
    p.add_argument("--concurrent", type=int, default=5)
    p.add_argument("--download-backend", default=None, choices=["auto", "gallery-dl", "httpx"])

    # dedup
    p = sub.add_parser("dedup")
    p.add_argument("--session", required=True)
    p.add_argument("--threshold", type=float, default=0.92)
    p.add_argument("--phash-threshold", type=int, default=10)
    p.add_argument("--clip", action="store_true")

    # analyze
    p = sub.add_parser("analyze")
    p.add_argument("--session", required=True)
    p.add_argument("--api-base", default="http://localhost:23333")
    p.add_argument("--api-key", default="")
    p.add_argument("--model", default="zhipu:glm-4.6v")

    # metrics
    p = sub.add_parser("metrics")
    p.add_argument("--session", required=True)
    p.add_argument("--api-base", default="http://localhost:23333")
    p.add_argument("--api-key", default="")
    p.add_argument("--model", default="zhipu:glm-4.6v")
    p.add_argument("--vlm", action="store_true", help="Also run VLM subjective analysis")
    p.add_argument("--force", action="store_true", help="Re-compute even if metrics file exists")

    # store
    p = sub.add_parser("store")
    p.add_argument("--session", required=True)
    p.add_argument("--topic", required=True)
    p.add_argument("--vector-backend", default=None, choices=["faiss", "lancedb"])

    # gallery
    p = sub.add_parser("gallery")
    p.add_argument("--topic", required=True, nargs="+")
    p.add_argument("--tags", nargs="*", default=None)
    p.add_argument("--min-score", type=float, default=None)

    # parse
    p = sub.add_parser("parse")
    p.add_argument("setting", nargs="?", default="", help="Setting text (or use --file)")
    p.add_argument("--file", default=None, help="Read setting from file")
    p.add_argument("--name", default=None, help="Board name (default: first 30 chars of setting)")
    p.add_argument("--api-base", default="http://localhost:23333")
    p.add_argument("--api-key", default="")
    p.add_argument("--model", default="zhipu:glm-4.6v")

    # plan
    p = sub.add_parser("plan")
    p.add_argument("--board", required=True, help="Board ID to plan references for")
    p.add_argument("--api-base", default="http://localhost:23333")
    p.add_argument("--api-key", default="")
    p.add_argument("--model", default="zhipu:glm-4.6v")

    # analyze-board
    p = sub.add_parser("analyze-board")
    p.add_argument("--board", required=True, help="Board ID")
    p.add_argument("--api-base", default="http://localhost:23333")
    p.add_argument("--api-key", default="")
    p.add_argument("--model", default="zhipu:glm-4.6v")
    p.add_argument("--status", default="candidate", help="Filter images by status")

    # rank
    p = sub.add_parser("rank")
    p.add_argument("--board", required=True, help="Board ID")
    p.add_argument("--phash-threshold", type=int, default=10)
    p.add_argument("--threshold", type=float, default=0.92)
    p.add_argument("--clip", action="store_true", help="Enable CLIP semantic dedup")

    # compose
    p = sub.add_parser("compose")
    p.add_argument("--board", required=True, help="Board ID")
    p.add_argument("--api-base", default="http://localhost:23333")
    p.add_argument("--api-key", default="")
    p.add_argument("--model", default="", help="VLM model for section summaries (skip if empty)")

    # reorder
    p = sub.add_parser("reorder")
    p.add_argument("--board", required=True, help="Board ID")
    p.add_argument("--section", required=True, help="Section ID (e.g. architecture)")
    p.add_argument("--order", required=True, nargs="+", help="Image IDs in desired order")

    # serve
    p = sub.add_parser("serve")
    p.add_argument("--port", type=int, default=8765, help="Port number (default: 8765)")

    # pipeline
    p = sub.add_parser("pipeline")
    p.add_argument("keywords")
    p.add_argument("--max", type=int, default=30)
    p.add_argument("--topic", required=True)
    p.add_argument("--model", default="zhipu:glm-4.6v")
    p.add_argument("--api-base", default="http://localhost:23333")
    p.add_argument("--region", default="wt-wt")
    p.add_argument("--phash-threshold", type=int, default=10)
    p.add_argument("--threshold", type=float, default=0.92)
    p.add_argument("--clip", action="store_true")
    p.add_argument("--search-backend", default=None, choices=["auto", "searxng", "duckduckgo"])
    p.add_argument("--download-backend", default=None, choices=["auto", "gallery-dl", "httpx"])
    p.add_argument("--vector-backend", default=None, choices=["faiss", "lancedb"])

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        "search": cmd_search,
        "download": cmd_download,
        "dedup": cmd_dedup,
        "analyze": cmd_analyze,
        "metrics": cmd_metrics,
        "store": cmd_store,
        "gallery": cmd_gallery,
        "parse": cmd_parse,
        "plan": cmd_plan,
        "analyze-board": cmd_analyze_board,
        "rank": cmd_rank,
        "compose": cmd_compose,
        "reorder": cmd_reorder,
        "serve": cmd_serve,
        "pipeline": cmd_pipeline,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
