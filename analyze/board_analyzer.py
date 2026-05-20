"""Board-aware Vision Analyzer — analyze images in context of a Board's setting."""

import base64
import json
import re
import sys
from pathlib import Path

import httpx
from tqdm import tqdm

from config import DEFAULT_API_BASE
from models.schemas import (
    BoardImage,
    CurationScores,
    ImageAnalysis,
    ImageCategoryScore,
    VisualMetrics,
)


BOARD_ANALYSIS_PROMPT = """你是一个资深概念美术参考图分析助手。

当前美术设定：
{setting_text}

当前画板视觉目标：
{visual_goal_summary}

当前参考线索：
{reference_track_info}

候选功能分类：
- mood: 整体氛围
- architecture: 建筑语言
- urban_layout: 城市布局
- interior: 室内空间
- materials: 材质纹理
- color_lighting: 色彩光照
- costume_character: 服装角色
- props: 道具器物
- symbols_patterns: 符号图案
- tech_machinery: 技术与机械
- landscape: 自然环境
- composition: 构图参考
- anti_reference: 负面参考（看起来相关但方向错误）

请分析图片，判断其作为概念美术参考的价值。

请输出严格 JSON：
{{
  "is_relevant": true,
  "relevance_score": 0.0,
  "functional_categories": [
    {{"category": "architecture", "score": 0.0, "reason": ""}}
  ],
  "visual_summary": "",
  "useful_elements": [],
  "style_tags": [],
  "material_tags": [],
  "color_palette_words": [],
  "composition_tags": [],
  "possible_risks": [],
  "avoid_copying": [],
  "recommended_board_section": [],
  "visual_metrics": {{
    "brightness": 0.5,
    "saturation": 0.5,
    "warmth": 0.5,
    "contrast": 0.5,
    "color_complexity": 0.5,
    "detail_density": 0.5,
    "shot_scale": 0.5,
    "openness": 0.5,
    "monumentality": 0.5,
    "religiousness": 0.5,
    "industrialness": 0.5,
    "decay": 0.5,
    "orderliness": 0.5,
    "fantasy_level": 0.5,
    "sci_fi_level": 0.5
  }},
  "curation_scores": {{
    "aesthetic_score": 0.0,
    "composition_score": 0.0,
    "lighting_score": 0.0,
    "design_reference_score": 0.0,
    "style_consistency_score": 0.0,
    "uniqueness_score": 0.0,
    "usability_score": 0.0,
    "risk_score": 0.0
  }},
  "final_recommendation": "core/reference/supplement/reject"
}}

要求：
1. relevance_score: 与当前设定的整体相关性 0-1
2. functional_categories: 判断图片适合哪些功能分类，每个给 0-1 分和理由
3. visual_summary: 简短视觉描述
4. useful_elements: 可提取的设计元素列表
5. style_tags/material_tags/color_palette_words/composition_tags: 各类标签
6. possible_risks: 版权、文化、风格风险
7. avoid_copying: 不应直接照搬的元素
8. visual_metrics: 15 个视觉维度评分，所有值 0-1
9. curation_scores: 策展评分，所有值 0-1
10. final_recommendation: core(核心参考) / reference(一般参考) / supplement(补充) / reject(拒绝)"""


def _encode_image(image_path: str) -> tuple[str, str]:
    ext = Path(image_path).suffix.lower()
    mime = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".webp": "image/webp",
        ".gif": "image/gif", ".bmp": "image/bmp",
    }.get(ext, "image/jpeg")
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return b64, mime


def _parse_json_response(content: str) -> dict:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return {}


def analyze_image_for_board(
    image_path: str,
    setting_text: str = "",
    visual_goal_summary: str = "",
    reference_track_info: str = "",
    api_base: str = DEFAULT_API_BASE,
    model: str = "",
    api_key: str = "",
) -> tuple[ImageAnalysis, list[ImageCategoryScore], CurationScores, VisualMetrics]:
    """Analyze a single image in board context.

    Returns (analysis, categories, curation_scores, visual_metrics).
    """
    prompt = BOARD_ANALYSIS_PROMPT.format(
        setting_text=setting_text or "（无特定设定）",
        visual_goal_summary=visual_goal_summary or "（无特定视觉目标）",
        reference_track_info=reference_track_info or "（无特定参考线索）",
    )

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
                    {"type": "text", "text": prompt},
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
    data = _parse_json_response(content)

    # Parse functional categories
    categories = []
    for cat_data in data.get("functional_categories", []):
        categories.append(ImageCategoryScore(
            category=cat_data.get("category", ""),
            score=_clamp(cat_data.get("score", 0.0)),
            reason=cat_data.get("reason", ""),
        ))

    # Parse visual metrics
    vm_raw = data.get("visual_metrics", {})
    visual_metrics = VisualMetrics(
        brightness=_clamp(vm_raw.get("brightness", 0.5)),
        saturation=_clamp(vm_raw.get("saturation", 0.5)),
        warmth=_clamp(vm_raw.get("warmth", 0.5)),
        contrast=_clamp(vm_raw.get("contrast", 0.5)),
        color_complexity=_clamp(vm_raw.get("color_complexity", 0.5)),
        detail_density=_clamp(vm_raw.get("detail_density", 0.5)),
        shot_scale=_clamp(vm_raw.get("shot_scale", 0.5)),
        openness=_clamp(vm_raw.get("openness", 0.5)),
        monumentality=_clamp(vm_raw.get("monumentality", 0.5)),
        religiousness=_clamp(vm_raw.get("religiousness", 0.5)),
        industrialness=_clamp(vm_raw.get("industrialness", 0.5)),
        decay=_clamp(vm_raw.get("decay", 0.5)),
        orderliness=_clamp(vm_raw.get("orderliness", 0.5)),
        fantasy_level=_clamp(vm_raw.get("fantasy_level", 0.5)),
        sci_fi_level=_clamp(vm_raw.get("sci_fi_level", 0.5)),
    )

    # Parse curation scores
    cs_raw = data.get("curation_scores", {})
    curation_scores = CurationScores(
        aesthetic_score=_clamp(cs_raw.get("aesthetic_score", 0.0)),
        composition_score=_clamp(cs_raw.get("composition_score", 0.0)),
        lighting_score=_clamp(cs_raw.get("lighting_score", 0.0)),
        design_reference_score=_clamp(cs_raw.get("design_reference_score", 0.0)),
        style_consistency_score=_clamp(cs_raw.get("style_consistency_score", 0.0)),
        uniqueness_score=_clamp(cs_raw.get("uniqueness_score", 0.0)),
        usability_score=_clamp(cs_raw.get("usability_score", 0.0)),
        risk_score=_clamp(cs_raw.get("risk_score", 0.0)),
    )

    # Parse analysis
    analysis = ImageAnalysis(
        is_relevant=data.get("is_relevant", True),
        relevance_score=_clamp(data.get("relevance_score", 0.0)),
        functional_categories=categories,
        visual_summary=data.get("visual_summary", ""),
        useful_elements=data.get("useful_elements", []),
        style_tags=data.get("style_tags", []),
        material_tags=data.get("material_tags", []),
        color_palette_words=data.get("color_palette_words", []),
        composition_tags=data.get("composition_tags", []),
        possible_risks=data.get("possible_risks", []),
        avoid_copying=data.get("avoid_copying", []),
        recommended_board_section=data.get("recommended_board_section", []),
        final_recommendation=data.get("final_recommendation", "reference"),
    )

    return analysis, categories, curation_scores, visual_metrics


def analyze_board_images(
    board_id: str,
    api_base: str = DEFAULT_API_BASE,
    model: str = "",
    api_key: str = "",
    status_filter: str | None = "candidate",
) -> list[BoardImage]:
    """Analyze all images in a board and update the database."""
    from store.database import ImageDatabase

    db = ImageDatabase()
    board = db.get_board(board_id)
    if not board:
        print(f"Board {board_id} not found", file=sys.stderr)
        db.close()
        return []

    images = db.get_board_images(board_id, status=status_filter)
    if not images:
        print("No images to analyze", file=sys.stderr)
        db.close()
        return []

    # Build reference track info for context
    track_info = ""
    if board.reference_tracks:
        tracks_summary = []
        for t in board.reference_tracks:
            tracks_summary.append(f"- {t.name}: {t.description}")
        track_info = "\n".join(tracks_summary)

    analyzed = []
    for img in tqdm(images, desc="Analyzing board images"):
        path = img.local_path
        if not path or not Path(path).exists():
            continue

        try:
            analysis, categories, curation, metrics = analyze_image_for_board(
                image_path=path,
                setting_text=board.setting_text,
                visual_goal_summary=board.visual_goal_summary,
                reference_track_info=track_info,
                api_base=api_base,
                model=model,
                api_key=api_key,
            )

            # Merge pixel metrics into visual metrics for higher accuracy
            _merge_pixel_metrics(path, metrics)

            # Update database
            db.update_image_analysis(img.id, analysis, categories, curation, metrics)

            # Update the in-memory image
            img.analysis = analysis
            img.categories = categories
            img.curation_scores = curation
            img.visual_metrics = metrics
            analyzed.append(img)

        except Exception as e:
            print(f"Failed to analyze {img.id}: {e}", file=sys.stderr)
            analyzed.append(img)

    db.close()
    return analyzed


def _merge_pixel_metrics(image_path: str, metrics: VisualMetrics) -> None:
    """Merge pixel-computed metrics into VLM-estimated metrics where pixel is more accurate."""
    try:
        from analyze.pixel_metrics import compute_all
        pixel = compute_all(image_path)
        # Pixel metrics are more reliable for these dimensions
        metrics.brightness = pixel.get("brightness", metrics.brightness)
        metrics.saturation = pixel.get("saturation", metrics.saturation)
        metrics.contrast = pixel.get("contrast", metrics.contrast)
        metrics.color_complexity = pixel.get("color_complexity", metrics.color_complexity)
    except Exception:
        pass  # Keep VLM estimates if pixel computation fails


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return 0.5
