"""Board Composer — organize analyzed images into a structured reference board."""

import json
import sys
from pathlib import Path
from collections import defaultdict

import httpx

from config import DEFAULT_API_BASE, DEFAULT_BOARD_TOP_K
from models.categories import CATEGORY_MAP
from models.schemas import (
    Board,
    BoardImage,
    BoardSection,
    KeyImageRef,
)


COMPOSER_PROMPT = """你是一个概念美术画板编排器。

你需要根据图片分析结果、功能分类、排序分数和当前设定，为每个功能分类区生成美术方向总结。

当前设定：
{setting_text}

当前视觉目标：
{visual_goal_summary}

分类：{section_id} — {section_name}

该分类下的图片分析摘要：
{image_summaries}

请输出严格 JSON：
{{
  "summary": "该分类的美术方向说明（2-4句话）",
  "design_takeaways": ["可借鉴的设计要点1", "要点2", ...],
  "missing_needs": ["缺失的参考方向1", ...]
}}

要求：
1. summary 要具体、有指导性，不要泛泛而谈
2. design_takeaways 应从图片中总结可操作的设计方向
3. missing_needs 指出该分类图片不足的地方"""


def _order_images(images: list[KeyImageRef], user_order: list[str]) -> list[KeyImageRef]:
    """Apply user_order to image list. Images not in user_order keep their relative position at the end."""
    if not user_order:
        return images
    order_map = {img_id: i for i, img_id in enumerate(user_order)}
    ordered = sorted(images, key=lambda x: order_map.get(x.image_id, len(user_order)))
    return ordered


def _group_images_by_category(images: list[BoardImage]) -> dict[str, list[BoardImage]]:
    """Group images by their primary functional category."""
    groups: dict[str, list[BoardImage]] = defaultdict(list)
    for img in images:
        if img.status in ("rejected", "duplicate"):
            continue
        for cat in img.categories:
            groups[cat.category].append(img)
        # Also add to recommended sections
        for section in (img.analysis.recommended_board_section if img.analysis else []):
            if img not in groups[section]:
                groups[section].append(img)
    return dict(groups)


def _select_section_images(
    images: list[BoardImage],
    top_k: int = 8,
    supporting_k: int = 16,
) -> tuple[list[BoardImage], list[BoardImage]]:
    """Select key and supporting images for a section, deduplicating similar images."""
    # Sort by final_score descending
    sorted_imgs = sorted(images, key=lambda x: x.final_score, reverse=True)
    key = []
    supporting = []

    for img in sorted_imgs:
        if img.status in ("rejected", "duplicate"):
            continue
        if len(key) < top_k:
            key.append(img)
        elif len(supporting) < supporting_k:
            supporting.append(img)
        else:
            break

    return key, supporting


def _build_image_summary(img: BoardImage) -> str:
    """Build a short summary string for an image."""
    parts = [f"[{img.id}]"]
    if img.analysis:
        parts.append(img.analysis.visual_summary)
        if img.analysis.useful_elements:
            parts.append(f"可用元素: {', '.join(img.analysis.useful_elements[:5])}")
    cats = [f"{c.category}={c.score:.2f}" for c in img.categories[:3]]
    if cats:
        parts.append(f"分类: {', '.join(cats)}")
    parts.append(f"分数: {img.final_score:.2f}")
    return " | ".join(parts)


def _generate_section_summary(
    section_id: str,
    section_name: str,
    images: list[BoardImage],
    setting_text: str,
    visual_goal_summary: str,
    api_base: str,
    model: str,
    api_key: str,
) -> dict:
    """Use VLM to generate section summary, design takeaways, and missing needs."""
    summaries = "\n".join(f"- {_build_image_summary(img)}" for img in images[:10])

    prompt = COMPOSER_PROMPT.format(
        setting_text=setting_text or "（无）",
        visual_goal_summary=visual_goal_summary or "（无）",
        section_id=section_id,
        section_name=section_name,
        image_summaries=summaries or "（无图片）",
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
                "max_tokens": 2048,
                "temperature": 0.4,
            },
            timeout=120.0,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
        return json.loads(cleaned)
    except Exception as e:
        print(f"  VLM summary failed for {section_id}: {e}", file=sys.stderr)
        return {"summary": "", "design_takeaways": [], "missing_needs": []}


def compose_board(
    board_id: str,
    api_base: str = DEFAULT_API_BASE,
    model: str = "",
    api_key: str = "",
) -> dict:
    """Compose a structured reference board from analyzed images."""
    from store.database import ImageDatabase

    db = ImageDatabase()
    board = db.get_board(board_id)
    if not board:
        db.close()
        return {"error": f"Board {board_id} not found"}

    images = db.get_board_images(board_id)
    active_images = [img for img in images if img.status not in ("rejected", "duplicate")]

    if not active_images:
        db.close()
        return {"error": "No active images to compose"}

    top_k = DEFAULT_BOARD_TOP_K

    # 1. Select core references (top-scoring images across all categories)
    core_candidates = [img for img in active_images if img.status in ("core", "curated")]
    core_candidates.sort(key=lambda x: x.final_score, reverse=True)
    core_refs = [
        KeyImageRef(image_id=img.id, reason=_build_core_reason(img))
        for img in core_candidates[:top_k["core_references"]]
    ]

    # 2. Select anti-references
    anti_images = [img for img in images if img.status == "anti" or
                   (img.analysis and img.analysis.final_recommendation == "reject" and img.analysis.is_relevant)]
    anti_refs = [
        KeyImageRef(image_id=img.id, reason=_build_anti_reason(img))
        for img in anti_images[:top_k["anti_references"]]
    ]

    # 3. Group images by functional category
    category_groups = _group_images_by_category(active_images)

    # 4. Build sections
    sections = []
    vlm_sections = []  # Sections that need VLM summaries

    for cat_id, cat_def in CATEGORY_MAP.items():
        if cat_id == "anti_reference":
            continue  # Handled separately

        cat_images = category_groups.get(cat_id, [])
        if not cat_images:
            # Empty section — still create it with missing_needs
            section = BoardSection(
                section_id=cat_id,
                section_name=cat_def.name,
                summary="",
                missing_needs=[f"缺少{cat_def.name}相关参考图片"],
            )
            sections.append(section)
            continue

        key, supporting = _select_section_images(
            cat_images, top_k["section_key_images"], top_k["section_supporting"]
        )

        # Check if user_order exists from previous composition
        existing_sections = db.get_sections(board_id)
        existing_user_order = []
        for es in existing_sections:
            if es.section_id == cat_id:
                existing_user_order = es.user_order
                break

        key_refs = _order_images(
            [KeyImageRef(image_id=img.id, reason=_build_key_reason(img)) for img in key],
            existing_user_order,
        )
        support_refs = _order_images(
            [KeyImageRef(image_id=img.id, reason=_build_support_reason(img)) for img in supporting],
            existing_user_order,
        )

        section = BoardSection(
            section_id=cat_id,
            section_name=cat_def.name,
            key_images=key_refs,
            supporting_images=support_refs,
            user_order=existing_user_order,
        )
        sections.append(section)
        if key:
            vlm_sections.append((section, key + supporting))

    # 5. Generate VLM summaries (single batch call per section)
    if model:
        from tqdm import tqdm
        for section, section_images in tqdm(vlm_sections, desc="Generating section summaries"):
            result = _generate_section_summary(
                section_id=section.section_id,
                section_name=section.section_name,
                images=section_images,
                setting_text=board.setting_text,
                visual_goal_summary=board.visual_goal_summary,
                api_base=api_base,
                model=model,
                api_key=api_key,
            )
            section.summary = result.get("summary", "")
            section.design_takeaways = result.get("design_takeaways", [])
            if result.get("missing_needs"):
                section.missing_needs = result["missing_needs"]

    # 6. Collect global missing needs
    global_missing = []
    next_search = []
    for s in sections:
        if not s.key_images and s.missing_needs:
            global_missing.extend(s.missing_needs)
    # Deduplicate
    global_missing = list(dict.fromkeys(global_missing))

    # 7. Generate next search suggestions from missing needs
    if global_missing and model:
        next_search = _generate_next_search_suggestions(
            global_missing, board.setting_text, api_base, model, api_key,
        )

    # 8. Save to database
    for section in sections:
        db.save_section(board_id, section)
    # Update board-level data
    board.core_references = core_refs
    board.anti_references = anti_refs
    board.sections = sections
    board.global_missing_needs = global_missing
    board.next_search_suggestions = next_search
    db.save_board(board)

    # 9. Export to board folder
    composition = {
        "board_id": board_id,
        "board_title": board.name,
        "visual_goal_summary": board.visual_goal_summary,
        "setting_text": board.setting_text,
        "core_references": [r.model_dump() for r in core_refs],
        "sections": [s.model_dump() for s in sections],
        "anti_references": [r.model_dump() for r in anti_refs],
        "global_missing_needs": global_missing,
        "next_search_suggestions": next_search,
    }

    if board.base_dir:
        comp_path = Path(board.base_dir) / "board_composition.json"
        comp_path.write_text(
            json.dumps(composition, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        # Also update _board.json
        board_json = db.export_board_json(board_id)
        if board_json:
            (Path(board.base_dir) / "_board.json").write_text(board_json, encoding="utf-8")

    db.close()

    return {
        "board_id": board_id,
        "core_count": len(core_refs),
        "sections": len(sections),
        "sections_with_images": sum(1 for s in sections if s.key_images),
        "global_missing": len(global_missing),
        "next_search": len(next_search),
    }


def _generate_next_search_suggestions(
    missing_needs: list[str],
    setting_text: str,
    api_base: str,
    model: str,
    api_key: str,
) -> list[str]:
    """Generate search suggestions from missing needs."""
    prompt = f"""根据以下缺失的参考方向，生成 3-6 个具体的英文搜索查询词，用于在下一轮搜索中补充参考图片。

当前设定：{setting_text}

缺失方向：
{chr(10).join(f'- {n}' for n in missing_needs)}

请输出一个 JSON 数组，每个元素是一个搜索查询字符串。只输出数组，不要其他文字。"""

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
                "max_tokens": 1024,
                "temperature": 0.4,
            },
            timeout=60.0,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0]
        return json.loads(content)
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Helper text generators
# ---------------------------------------------------------------------------

def _build_core_reason(img: BoardImage) -> str:
    if img.analysis and img.analysis.visual_summary:
        return img.analysis.visual_summary[:80]
    return f"分数 {img.final_score:.2f}"

def _build_key_reason(img: BoardImage) -> str:
    if img.categories:
        top = max(img.categories, key=lambda c: c.score)
        return top.reason or f"{top.category}={top.score:.2f}"
    return ""

def _build_support_reason(img: BoardImage) -> str:
    if img.analysis and img.analysis.useful_elements:
        return ", ".join(img.analysis.useful_elements[:3])
    return ""

def _build_anti_reason(img: BoardImage) -> str:
    if img.analysis and img.analysis.possible_risks:
        return img.analysis.possible_risks[0]
    return "方向偏差"
