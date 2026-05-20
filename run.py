import argparse
import json
import sys
import uuid
from pathlib import Path

from config import DATA_DIR, SESSIONS_DIR


def ensure_dirs():
    for d in [DATA_DIR / "images", DATA_DIR / "thumbnails", SESSIONS_DIR,
              DATA_DIR / "faiss_index", DATA_DIR / "lancedb",
              DATA_DIR / "galleries", DATA_DIR / "metrics"]:
        d.mkdir(parents=True, exist_ok=True)


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
        "pipeline": cmd_pipeline,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
