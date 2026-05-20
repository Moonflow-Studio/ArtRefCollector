import base64
import json
import sys
from pathlib import Path

import httpx
from tqdm import tqdm

from config import VISION_PROMPT


def _encode_image(image_path: str) -> str:
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _infer_mime_type(path: str) -> str:
    ext = Path(path).suffix.lower()
    return {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".webp": "image/webp",
        ".gif": "image/gif", ".bmp": "image/bmp",
    }.get(ext, "image/jpeg")


def tag_image(
    image_path: str,
    api_base: str = "http://localhost:23456",
    model: str = "openai:gpt-4o",
    api_key: str = "",
) -> dict:
    b64 = _encode_image(image_path)
    mime = _infer_mime_type(image_path)

    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    resp = httpx.post(
        f"{api_base}/v1/chat/completions",
        headers=headers,
        json={
            "model": model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": VISION_PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                ],
            }],
            "max_tokens": 4096,
            "temperature": 0.3,
        },
        timeout=120.0,
    )
    resp.raise_for_status()

    content = resp.json()["choices"][0]["message"]["content"]
    try:
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {"description": content, "tags": [], "quality_score": 0}


def tag_images(
    images: list[dict],
    api_base: str = "http://localhost:23456",
    model: str = "openai:gpt-4o",
    api_key: str = "",
) -> list[dict]:
    results = []
    for item in tqdm(images, desc="Analyzing images"):
        if item.get("status") != "success":
            results.append(item)
            continue

        path = item.get("local_path", "")
        if not path or not Path(path).exists():
            results.append(item)
            continue

        try:
            analysis = tag_image(path, api_base, model, api_key)
            results.append({**item, **analysis})
        except Exception as e:
            print(f"Failed to analyze {path}: {e}", file=sys.stderr)
            results.append({**item, "analysis_error": str(e)})

    return results
