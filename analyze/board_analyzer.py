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
    PerceptualDimensions,
    PixelMetrics,
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
  "perceptual_dimensions": {{
    "shot_scale": 0.5,
    "spatial_scale": 0.5,
    "openness": 0.5,
    "style": 0.5,
    "ornateness": 0.5,
    "orderliness": 0.5,
    "emotion_intensity": 0.5,
    "warmth": 0.5,
    "material_roughness": 0.5,
    "decay": 0.5,
    "era_feel": 0.5,
    "industrialness": 0.5,
    "religiousness": 0.5,
    "fantasy_level": 0.5,
    "sci_fi_level": 0.5
  }},
  "risk_score": 0.0,
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
8. perceptual_dimensions: 15个感知维度评分，所有值 0-1，每个维度代表一个语义轴：
   - shot_scale: 景别 (0=远景, 0.33=中景, 0.66=近景, 1.0=特写)
   - spatial_scale: 空间尺度 (0=私密狭小, 1=宏大开阔)
   - openness: 开放感 (0=封闭压迫, 1=开阔通透)
   - style: 风格化程度 (0=写实, 0.5=风格化写实, 1.0=高度风格化)
   - ornateness: 装饰程度 (0=朴素极简, 1=华丽繁复)
   - orderliness: 秩序感 (0=混乱有机, 1=规整几何)
   - emotion_intensity: 情绪强度 (0=平静中性, 1=紧张强烈)
   - warmth: 色温氛围的主观感受 (0=冷酷, 1=温暖)
   - material_roughness: 材质粗度 (0=精致抛光, 1=粗粝原始)
   - decay: 破败度 (0=完好如新, 1=风化破败)
   - era_feel: 时代感 (0=古典, 0.5=当代, 1.0=未来)
   - industrialness: 工业感 (0=自然有机, 1=工业机械)
   - religiousness: 宗教感 (0=世俗, 1=神圣仪式)
   - fantasy_level: 奇幻程度 (0=日常现实, 1=高奇幻)
   - sci_fi_level: 科幻程度 (0=前科技, 1=先进科幻)
9. risk_score: 整体风险分 0-1
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
) -> tuple[ImageAnalysis, list[ImageCategoryScore], PerceptualDimensions, float, PixelMetrics]:
    """Analyze a single image in board context.

    Returns (analysis, categories, perceptual_dimensions, risk_score, pixel_metrics).
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

    # Parse perceptual dimensions
    pd_raw = data.get("perceptual_dimensions", {})
    perceptual = PerceptualDimensions(
        shot_scale=_clamp(pd_raw.get("shot_scale", 0.5)),
        spatial_scale=_clamp(pd_raw.get("spatial_scale", 0.5)),
        openness=_clamp(pd_raw.get("openness", 0.5)),
        style=_clamp(pd_raw.get("style", 0.5)),
        ornateness=_clamp(pd_raw.get("ornateness", 0.5)),
        orderliness=_clamp(pd_raw.get("orderliness", 0.5)),
        emotion_intensity=_clamp(pd_raw.get("emotion_intensity", 0.5)),
        warmth=_clamp(pd_raw.get("warmth", 0.5)),
        material_roughness=_clamp(pd_raw.get("material_roughness", 0.5)),
        decay=_clamp(pd_raw.get("decay", 0.5)),
        era_feel=_clamp(pd_raw.get("era_feel", 0.5)),
        industrialness=_clamp(pd_raw.get("industrialness", 0.5)),
        religiousness=_clamp(pd_raw.get("religiousness", 0.5)),
        fantasy_level=_clamp(pd_raw.get("fantasy_level", 0.5)),
        sci_fi_level=_clamp(pd_raw.get("sci_fi_level", 0.5)),
    )

    risk_score = _clamp(data.get("risk_score", 0.0))

    # Compute pixel metrics
    pixel = _compute_pixel_metrics(image_path)

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

    return analysis, categories, perceptual, risk_score, pixel


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
            analysis, categories, perceptual, risk_score, pixel = analyze_image_for_board(
                image_path=path,
                setting_text=board.setting_text,
                visual_goal_summary=board.visual_goal_summary,
                reference_track_info=track_info,
                api_base=api_base,
                model=model,
                api_key=api_key,
            )

            # Update database with new fields
            db.update_image_v5_analysis(
                img.id, analysis, categories, perceptual, risk_score, pixel,
            )

            # Also update legacy fields for backward compat
            legacy_curation = CurationScores(risk_score=risk_score)
            legacy_vm = _build_legacy_visual_metrics(perceptual, pixel)
            db.update_image_analysis(img.id, analysis, categories, legacy_curation, legacy_vm)

            # Update the in-memory image
            img.analysis = analysis
            img.categories = categories
            img.perceptual_dimensions = perceptual
            img.pixel_metrics = pixel
            img.curation_scores = legacy_curation
            img.visual_metrics = legacy_vm
            analyzed.append(img)

        except Exception as e:
            print(f"Failed to analyze {img.id}: {e}", file=sys.stderr)
            analyzed.append(img)

    db.close()
    return analyzed


def _compute_pixel_metrics(image_path: str) -> PixelMetrics:
    """Compute pixel-level metrics from the image file."""
    try:
        from analyze.pixel_metrics import compute_all
        pixel = compute_all(image_path)
        return PixelMetrics(
            brightness=pixel.get("brightness", 0.5),
            saturation=pixel.get("saturation", 0.5),
            color_temperature=pixel.get("color_temperature", 0.5),
            dominant_hue=pixel.get("dominant_hue", 0.5),
            contrast=pixel.get("contrast", 0.5),
            color_complexity=pixel.get("color_complexity", 0.5),
            edge_density=pixel.get("edge_density", 0.5),
            texture_complexity=pixel.get("texture_complexity", 0.5),
            composition_x=pixel.get("composition_x", 0.5),
            composition_y=pixel.get("composition_y", 0.5),
            spatial_openness=pixel.get("spatial_openness", 0.5),
            human_ratio=pixel.get("human_ratio", 0.0),
        )
    except Exception:
        return PixelMetrics()


def _build_legacy_visual_metrics(
    perceptual: PerceptualDimensions,
    pixel: PixelMetrics,
) -> VisualMetrics:
    """Build legacy VisualMetrics from new fields for backward compat."""
    return VisualMetrics(
        brightness=pixel.brightness,
        saturation=pixel.saturation,
        warmth=perceptual.warmth,
        contrast=pixel.contrast,
        color_complexity=pixel.color_complexity,
        detail_density=_clamp((pixel.edge_density + pixel.texture_complexity) / 2),
        shot_scale=perceptual.shot_scale,
        openness=perceptual.openness,
        monumentality=perceptual.spatial_scale,
        religiousness=perceptual.religiousness,
        industrialness=perceptual.industrialness,
        decay=perceptual.decay,
        orderliness=perceptual.orderliness,
        fantasy_level=perceptual.fantasy_level,
        sci_fi_level=perceptual.sci_fi_level,
    )


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return 0.5
