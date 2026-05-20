"""Batch search with rate-limit handling and retry logic."""
import json
import sys
import time
import uuid
from pathlib import Path

from config import DATA_DIR, SESSIONS_DIR


def new_session() -> str:
    sid = uuid.uuid4().hex[:12]
    session_dir = SESSIONS_DIR / sid
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "search_results.json").write_text("[]")
    (session_dir / "downloads.json").write_text("[]")
    return sid


def save_session_data(sid: str, filename: str, data):
    path = SESSIONS_DIR / sid / filename
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def search_with_retry(keywords, max_results=10, max_retries=3, delay=15, **kwargs):
    from search.duckduckgo_searcher import search_images
    for attempt in range(max_retries):
        try:
            results = search_images(keywords=keywords, max_results=max_results, **kwargs)
            return results
        except Exception as e:
            if attempt < max_retries - 1:
                wait = delay * (attempt + 1)
                print(f"  Retry {attempt+1}/{max_retries} after {wait}s: {e}", file=sys.stderr)
                time.sleep(wait)
            else:
                print(f"  FAILED after {max_retries} retries: {keywords}", file=sys.stderr)
                return []


def merge_sessions(session_ids, merged_id):
    """Merge multiple sessions into one."""
    all_results = []
    seen_urls = set()
    for sid in session_ids:
        path = SESSIONS_DIR / sid / "search_results.json"
        if path.exists():
            results = json.loads(path.read_text())
            for r in results:
                url = r.get("image_url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_results.append(r)
    save_session_data(merged_id, "search_results.json", all_results)
    return len(all_results)


SCENES = {
    "S3_屏蔽室": [
        "Barbican Centre London concrete corridor",
        "James Turrell Skyspace light installation",
        "NASA cleanroom airlock",
        "brutalist bunker interior concrete",
        "Tadao Ando concrete church light cross",
    ],
    "S1_焰砂海矿营": [
        "Monument Valley afternoon long shadows desert",
        "Coober Pedy Australia mining town desert",
        "Bodie ghost town California abandoned mining",
        "Nevada desert mining camp ghost town",
        "Edward Hopper sunlight buildings afternoon",
        "Australian outback red dirt desert landscape",
    ],
    "S7_冠脊林活矿林": [
        "Sequoia National Park sunbeams forest light rays",
        "Icelandic moss landscape lava field",
        "Ashikaga Flower Park wisteria tunnel Japan",
        "Hoh Rain Forest moss floor Olympic",
        "malachite vein in rock copper ore exposed",
        "Hallerbos Belgium bluebell forest morning light",
        "Waitomo Glowworm Caves New Zealand bioluminescent",
    ],
}

SEARCH_DELAY = 20  # seconds between searches


def main():
    for scene_name, keywords_list in SCENES.items():
        print(f"\n{'='*60}")
        print(f"Scene: {scene_name}")
        print(f"{'='*60}")

        merged_id = new_session()
        sub_sessions = []

        for i, kw in enumerate(keywords_list):
            print(f"\n[{i+1}/{len(keywords_list)}] Searching: {kw}")
            sid = new_session()
            results = search_with_retry(
                keywords=kw,
                max_results=10,
                max_retries=3,
                delay=SEARCH_DELAY,
                type_image="photo",
                layout="Wide",
            )
            save_session_data(sid, "search_results.json", results)
            sub_sessions.append(sid)
            print(f"  Found {len(results)} results (session: {sid})")

            if i < len(keywords_list) - 1:
                print(f"  Waiting {SEARCH_DELAY}s before next search...")
                time.sleep(SEARCH_DELAY)

        count = merge_sessions(sub_sessions, merged_id)
        print(f"\n=> Merged session: {merged_id} | Total unique results: {count}")
        print(f"   Topic: {scene_name}")

    print("\n\nAll searches complete!")


if __name__ == "__main__":
    main()
