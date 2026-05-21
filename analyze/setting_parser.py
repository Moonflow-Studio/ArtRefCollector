"""Setting Parser — extract structured visual requirements from text settings."""

import json
import math
import re
import sys
from datetime import datetime

import httpx

from config import DEFAULT_API_BASE, PERCEPTUAL_DIMENSION_DEFS
from models.schemas import (
    BoardCenterValues,
    DimensionCenter,
    SettingParseResult,
    StyleProfile,
)


SETTING_PARSER_PROMPT = """你是一个概念美术设定解析器。

请根据用户输入的美术设定，提取其中的视觉目标、参考来源、设计维度和潜在缺口。

你需要输出严格 JSON，不要输出额外解释。

用户设定：
{setting_text}

输出格式：
{{
  "core_concepts": [],
  "visual_dimensions": [],
  "known_references": [],
  "implicit_references": [],
  "missing_references": [],
  "style_profile": {{
    "mood": [],
    "architecture": [],
    "color": [],
    "materials": [],
    "lighting": [],
    "composition": [],
    "avoid": []
  }},
  "avoid_directions": [],
  "clarification_questions": []
}}

要求：
1. core_concepts: 设定中的核心视觉概念（英文，用于搜索）
2. visual_dimensions: 涉及的功能维度（从 mood/architecture/urban_layout/interior/materials/color_lighting/costume_character/props/symbols_patterns/tech_machinery/landscape/composition 中选取）
3. known_references: 设定中明确提到的参考来源
4. implicit_references: 设定中隐含但未明说的参考来源
5. missing_references: 设定中缺少但需要的参考
6. style_profile: 各维度的风格标签
7. avoid_directions: 不应采用的视觉方向
8. clarification_questions: 需要用户进一步澄清的问题"""


def parse_setting(
    setting_text: str,
    api_base: str = DEFAULT_API_BASE,
    model: str = "",
    api_key: str = "",
) -> SettingParseResult:
    """Parse a text setting into structured visual requirements."""
    prompt = SETTING_PARSER_PROMPT.format(setting_text=setting_text)

    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    resp = httpx.post(
        f"{api_base}/v1/chat/completions",
        headers=headers,
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 4096,
            "temperature": 0.3,
        },
        timeout=120.0,
    )
    resp.raise_for_status()

    content = resp.json()["choices"][0]["message"]["content"]
    data = _parse_json_response(content)

    return SettingParseResult(
        core_concepts=data.get("core_concepts", []),
        visual_dimensions=data.get("visual_dimensions", []),
        known_references=data.get("known_references", []),
        implicit_references=data.get("implicit_references", []),
        missing_references=data.get("missing_references", []),
        style_profile=StyleProfile(**data.get("style_profile", {})),
        avoid_directions=data.get("avoid_directions", []),
        clarification_questions=data.get("clarification_questions", []),
    )


def _parse_json_response(content: str) -> dict:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Try to find JSON object in the response
    match = re.search(r"\{[\s\S]*\}", cleaned)
    if match:
        text = match.group()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # Try progressive truncation — remove last item until valid
        for _ in range(20):
            # Remove last element after last comma
            last_brace = text.rfind("}")
            if last_brace < 0:
                break
            text = text[:last_brace].rstrip()
            # Remove trailing comma
            text = text.rstrip(",").rstrip()
            # Close the array and object
            candidate = text + "}]}"
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
    return {}


# ---------------------------------------------------------------------------
# Center Value Derivation
# ---------------------------------------------------------------------------

_CENTER_VALUE_PROMPT = """你是一个概念美术设定解析器，擅长将文字氛围描述转化为精确的数值目标。

当前美术设定：
{setting_text}

对于以下每个感知维度，请根据设定文本推导出一个"中心值"（0-1之间的浮点数），代表这个设定在该维度上的理想值。同时给出一个权重（1-5），表示该维度对整体视觉风格的重要性，以及容差（0.1-0.8），表示设定对该维度的宽容度。

维度定义：
- shot_scale: 景别 (0=远景, 0.33=中景, 0.66=近景, 1.0=特写)
- spatial_scale: 空间尺度 (0=私密狭小, 1=宏大开阔)
- openness: 开放感 (0=封闭压迫, 1=开阔通透)
- style: 风格化程度 (0=写实, 0.5=风格化写实, 1.0=高度风格化)
- ornateness: 装饰程度 (0=朴素极简, 1=华丽繁复)
- orderliness: 秩序感 (0=混乱有机, 1=规整几何)
- emotion_intensity: 情绪强度 (0=平静中性, 1=紧张强烈)
- warmth: 色温氛围 (0=冷酷无菌, 1=温暖舒适)
- material_roughness: 材质粗度 (0=精致抛光, 1=粗粝原始)
- decay: 破败度 (0=完好如新, 1=风化破败)
- era_feel: 时代感 (0=古典, 0.5=当代, 1.0=未来)
- industrialness: 工业感 (0=自然有机, 1=工业机械)
- religiousness: 宗教感 (0=世俗, 1=神圣仪式)
- fantasy_level: 奇幻程度 (0=日常现实, 1=高奇幻)
- sci_fi_level: 科幻程度 (0=前科技, 1=先进科幻)

请输出严格 JSON：
{{
  "centers": [
    {{"dimension": "warmth", "center": 0.35, "weight": 3.0, "tolerance": 0.25, "reason": "冷寂但不幽恐的氛围暗示偏冷但非极端"}},
    ...
  ]
}}

要求：
1. 只输出与设定明确相关的维度，不相关的维度可以省略（省略的维度不参与距离评分）
2. center 值必须严格基于设定文本推导，不要凭空猜测
3. weight 反映该维度在设定中的重要程度（1=次要, 3=重要, 5=核心）
4. tolerance 反映设定对该维度的宽容度（0.1=极为严格, 0.5=较为宽松）
5. 为每个维度提供简短的 reason 说明推导依据"""


def derive_center_values(
    setting_text: str,
    api_base: str = DEFAULT_API_BASE,
    model: str = "",
    api_key: str = "",
) -> BoardCenterValues:
    """Derive perceptual dimension center values from setting text via VLM."""
    prompt = _CENTER_VALUE_PROMPT.format(setting_text=setting_text)

    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    resp = httpx.post(
        f"{api_base}/v1/chat/completions",
        headers=headers,
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 8192,
            "temperature": 0.3,
        },
        timeout=180.0,
    )
    resp.raise_for_status()

    content = resp.json()["choices"][0]["message"]["content"]
    data = _parse_json_response(content)

    centers = []
    for item in data.get("centers", []):
        dim = item.get("dimension", "")
        if dim in PERCEPTUAL_DIMENSION_DEFS:
            centers.append(DimensionCenter(
                dimension=dim,
                center=max(0.0, min(1.0, float(item.get("center", 0.5)))),
                weight=max(0.0, min(5.0, float(item.get("weight", 1.0)))),
                tolerance=max(0.05, min(1.0, float(item.get("tolerance", 0.3)))),
                reason=item.get("reason", ""),
            ))

    return BoardCenterValues(
        centers=centers,
        source="ai_derived",
        derived_at=datetime.now().isoformat(),
    )


# ---------------------------------------------------------------------------
# Feedback-based center value derivation (math + AI hybrid)
# ---------------------------------------------------------------------------

_FEEDBACK_ANALYSIS_PROMPT = """你是一个概念美术参考分析专家。

用户对一个美术参考Board中的图片进行了手动排序，靠前的图片代表更符合需求的参考。

美术设定：
{setting_text}

排序靠前的图片（用户认为参考性更强）的感知维度值：
{top_images}

排序靠后的图片（用户认为参考性较弱）的感知维度值：
{bottom_images}

数学推导的初步中心值：
{math_centers}

请根据用户的排序偏好，分析用户真正在意的视觉特征，调整各维度的中心值和权重。

输出严格 JSON：
{{
  "analysis": "简述你从用户排序中发现的偏好模式",
  "centers": [
    {{"dimension": "warmth", "center": 0.30, "weight": 4.0, "tolerance": 0.20, "reason": "用户偏好的图片明显偏冷色调"}},
    ...
  ]
}}

要求：
1. 分析靠前和靠后图片在各维度上的差异
2. 中心值可以调整但不要偏离数学推导太远
3. 权重应反映用户排序中体现的重视程度
4. 可以增加数学推导中省略的维度（如果排序明显受其影响）
5. 可以减少数学推导中包含的维度（如果排序不受其影响）"""


def derive_centers_from_feedback(
    setting_text: str,
    ordered_images: list,  # list of (BoardImage, rank_weight) tuples
    api_base: str = DEFAULT_API_BASE,
    model: str = "",
    api_key: str = "",
) -> BoardCenterValues:
    """Derive center values from user's manual reordering (math + AI hybrid).

    Step 1: Math — weighted average of top-ranked images' dimension values.
    Step 2: AI — VLM analyzes top/bottom images to refine centers.
    """
    if not ordered_images:
        return BoardCenterValues()

    # --- Step 1: Math derivation ---
    math_centers = _math_derive_centers(ordered_images)
    math_centers_text = json.dumps(
        [{"dimension": c.dimension, "center": c.center, "weight": c.weight,
          "tolerance": c.tolerance}
         for c in math_centers],
        ensure_ascii=False, indent=2,
    )

    # --- Step 2: AI refinement ---
    top_items = ordered_images[:5]
    bottom_items = ordered_images[-5:] if len(ordered_images) > 5 else ordered_images[:1]

    top_text = _format_images_dims(top_items)
    bottom_text = _format_images_dims(bottom_items)

    prompt = _FEEDBACK_ANALYSIS_PROMPT.format(
        setting_text=setting_text[:2000],
        top_images=top_text,
        bottom_images=bottom_text,
        math_centers=math_centers_text,
    )

    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        resp = httpx.post(
            f"{api_base}/v1/chat/completions",
            headers=headers,
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 4096,
                "temperature": 0.3,
            },
            timeout=120.0,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        data = _parse_json_response(content)

        ai_centers = []
        for item in data.get("centers", []):
            dim = item.get("dimension", "")
            if dim in PERCEPTUAL_DIMENSION_DEFS:
                ai_centers.append(DimensionCenter(
                    dimension=dim,
                    center=max(0.0, min(1.0, float(item.get("center", 0.5)))),
                    weight=max(0.0, min(5.0, float(item.get("weight", 1.0)))),
                    tolerance=max(0.05, min(1.0, float(item.get("tolerance", 0.3)))),
                    reason=item.get("reason", ""),
                ))

        if ai_centers:
            return _merge_centers(math_centers, ai_centers)
    except Exception:
        pass  # Fall back to math-only if AI fails

    return BoardCenterValues(
        centers=math_centers,
        source="user_feedback",
        derived_at=datetime.now().isoformat(),
    )


def merge_center_values(
    ai_centers: BoardCenterValues,
    feedback_centers: BoardCenterValues,
    feedback_weight: float = 0.6,
) -> BoardCenterValues:
    """Merge AI-derived and user-feedback center values."""
    ai_map = {c.dimension: c for c in ai_centers.centers}
    fb_map = {c.dimension: c for c in feedback_centers.centers}
    all_dims = set(ai_map.keys()) | set(fb_map.keys())

    merged = []
    w_ai = 1.0 - feedback_weight
    w_fb = feedback_weight

    for dim in all_dims:
        ai = ai_map.get(dim)
        fb = fb_map.get(dim)

        if ai and fb:
            merged.append(DimensionCenter(
                dimension=dim,
                center=round(ai.center * w_ai + fb.center * w_fb, 3),
                weight=round(ai.weight * w_ai + fb.weight * w_fb, 2),
                tolerance=round(ai.tolerance * w_ai + fb.tolerance * w_fb, 3),
                reason=fb.reason or ai.reason,
            ))
        elif fb:
            merged.append(fb)
        else:
            merged.append(ai)

    return BoardCenterValues(
        centers=merged,
        source="merged",
        derived_at=datetime.now().isoformat(),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _math_derive_centers(ordered_images: list) -> list[DimensionCenter]:
    """Compute center values as weighted average from rank-ordered images."""
    dim_values: dict[str, list[tuple[float, float]]] = {}  # dim -> [(value, weight)]

    for img, w in ordered_images:
        pd = img.perceptual_dimensions if hasattr(img, "perceptual_dimensions") else None
        if pd is None:
            continue
        for field_name in PERCEPTUAL_DIMENSION_DEFS:
            val = getattr(pd, field_name, 0.5)
            if val is None or val == 0.5:
                continue
            if field_name not in dim_values:
                dim_values[field_name] = []
            dim_values[field_name].append((val, w))

    centers = []
    for dim_name, vw_pairs in dim_values.items():
        if not vw_pairs:
            continue
        total_w = sum(w for _, w in vw_pairs)
        center = sum(v * w for v, w in vw_pairs) / total_w

        # Tolerance from standard deviation
        if len(vw_pairs) > 1:
            variance = sum(w * (v - center) ** 2 for v, w in vw_pairs) / total_w
            std = math.sqrt(variance)
            tolerance = max(0.1, min(0.8, std * 2.0))
        else:
            tolerance = 0.3

        # Weight from coverage
        coverage = len(vw_pairs) / len(ordered_images)
        weight = min(5.0, max(1.0, coverage * 5.0))

        centers.append(DimensionCenter(
            dimension=dim_name,
            center=round(center, 3),
            weight=round(weight, 2),
            tolerance=round(tolerance, 3),
        ))

    return centers


def _merge_centers(math_centers: list[DimensionCenter], ai_centers: list[DimensionCenter],
                   ai_weight: float = 0.5) -> BoardCenterValues:
    """Merge math-derived and AI-refined centers."""
    math_map = {c.dimension: c for c in math_centers}
    ai_map = {c.dimension: c for c in ai_centers}
    all_dims = set(math_map.keys()) | set(ai_map.keys())

    merged = []
    w_math = 1.0 - ai_weight
    for dim in all_dims:
        mc = math_map.get(dim)
        ac = ai_map.get(dim)
        if mc and ac:
            merged.append(DimensionCenter(
                dimension=dim,
                center=round(mc.center * w_math + ac.center * ai_weight, 3),
                weight=round(mc.weight * w_math + ac.weight * ai_weight, 2),
                tolerance=round(mc.tolerance * w_math + ac.tolerance * ai_weight, 3),
                reason=ac.reason or mc.reason,
            ))
        elif ac:
            merged.append(ac)
        else:
            merged.append(mc)

    return BoardCenterValues(
        centers=merged,
        source="user_feedback",
        derived_at=datetime.now().isoformat(),
    )


def _format_images_dims(items: list) -> str:
    """Format a list of (BoardImage, weight) as readable dimension values."""
    lines = []
    for img, w in items:
        pd = img.perceptual_dimensions if hasattr(img, "perceptual_dimensions") else None
        if pd is None:
            continue
        dims = {}
        for field_name in PERCEPTUAL_DIMENSION_DEFS:
            val = getattr(pd, field_name, 0.5)
            if val is not None and val != 0.5:
                label = PERCEPTUAL_DIMENSION_DEFS[field_name]["label"]
                dims[label] = round(val, 2)
        summary = img.analysis.visual_summary[:60] if hasattr(img, "analysis") and img.analysis else ""
        lines.append(f"- [{img.id}] {summary}\n  {json.dumps(dims, ensure_ascii=False)}")
    return "\n".join(lines)
