"""Vision model subjective metrics for art reference images.

Uses Cherry Studio API to rate each image on subjective dimensions.
All metrics are normalized to 0-1 range.
"""
import base64
import json
from pathlib import Path

import httpx

VLM_PROMPT = """Rate this art reference image on each dimension below.
Return ONLY a JSON object with these exact keys, each a float 0.0-1.0:

{
  "shot_scale":        "远景(0) ↔ 中景(0.33) ↔ 近景(0.66) ↔ 特写(1)",
  "spatial_scale":     "私密(0) ↔ 宏大(1)",
  "emotion_intensity": "平静(0) ↔ 紧张(1)",
  "oppression":        "开放(0) ↔ 压迫(1)",
  "religiousness":     "弱(0) ↔ 强(1)",
  "industrialness":    "弱(0) ↔ 强(1)",
  "fantasy_level":     "现实(0) ↔ 奇幻(1)",
  "sci_fi_level":      "现实(0) ↔ 科幻(1)",
  "decay_level":       "完整(0) ↔ 破败(1)",
  "orderliness":       "混乱(0) ↔ 规整(1)",
  "ornateness":        "朴素(0) ↔ 华丽(1)",
  "material_roughness":"精致(0) ↔ 粗粝(1)",
  "era_feel":          "古典(0) ↔ 现代(0.5) ↔ 未来(1)",
  "reference_value":   "弱参考(0) ↔ 强参考(1)"
}

Return ONLY the JSON object, no other text."""

SUBJECTIVE_AXES = {
    "shot_scale":        {"axis": "远景 ↔ 中景 ↔ 近景 ↔ 特写",   "label_low": "远景", "label_high": "特写"},
    "spatial_scale":     {"axis": "私密 ↔ 宏大",                 "label_low": "私密", "label_high": "宏大"},
    "emotion_intensity": {"axis": "平静 ↔ 紧张",                 "label_low": "平静", "label_high": "紧张"},
    "oppression":        {"axis": "开放 ↔ 压迫",                 "label_low": "开放", "label_high": "压迫"},
    "religiousness":     {"axis": "弱 ↔ 强",                     "label_low": "弱",   "label_high": "强"},
    "industrialness":    {"axis": "弱 ↔ 强",                     "label_low": "弱",   "label_high": "强"},
    "fantasy_level":     {"axis": "现实 ↔ 奇幻",                 "label_low": "现实", "label_high": "奇幻"},
    "sci_fi_level":      {"axis": "现实 ↔ 科幻",                 "label_low": "现实", "label_high": "科幻"},
    "decay_level":       {"axis": "完整 ↔ 破败",                 "label_low": "完整", "label_high": "破败"},
    "orderliness":       {"axis": "混乱 ↔ 规整",                 "label_low": "混乱", "label_high": "规整"},
    "ornateness":        {"axis": "朴素 ↔ 华丽",                 "label_low": "朴素", "label_high": "华丽"},
    "material_roughness":{"axis": "精致 ↔ 粗粝",                 "label_low": "精致", "label_high": "粗粝"},
    "era_feel":          {"axis": "古典 ↔ 现代 ↔ 未来",          "label_low": "古典", "label_high": "未来"},
    "reference_value":   {"axis": "弱参考 ↔ 强参考",             "label_low": "弱参考", "label_high": "强参考"},
}

EXPECTED_KEYS = list(SUBJECTIVE_AXES.keys())


def _encode_image(image_path: str) -> tuple[str, str]:
    ext = Path(image_path).suffix.lower()
    mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
            ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp"}.get(ext, "image/jpeg")
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return b64, mime


def analyze_subjective(
    image_path: str,
    api_base: str = "http://localhost:23333",
    model: str = "zhipu:glm-4.6v",
    api_key: str = "",
) -> dict:
    """Ask VLM to rate image on subjective dimensions. Returns dict of 0-1 floats."""
    b64, mime = _encode_image(image_path)

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
                    {"type": "text", "text": VLM_PROMPT},
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
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to extract JSON from text
        import re
        m = re.search(r'\{[^{}]+\}', cleaned, re.DOTALL)
        if m:
            parsed = json.loads(m.group())
        else:
            return {k: 0.5 for k in EXPECTED_KEYS}

    result = {}
    for k in EXPECTED_KEYS:
        v = parsed.get(k, 0.5)
        result[k] = round(max(0.0, min(1.0, float(v))), 4)
    return result
