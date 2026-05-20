"""Reference Planner — generate Reference Tracks from parsed settings."""

import json
import re
import uuid

import httpx

from config import DEFAULT_API_BASE
from models.categories import CATEGORY_IDS
from models.schemas import ReferenceTrack, SettingParseResult


REFERENCE_PLANNER_PROMPT = """你是一个概念美术参考规划器。

请根据设定解析结果，生成可执行的 Reference Tracks。

每个 Reference Track 必须包含：
- name: 参考线索名称
- source_type: 来源类型（从以下选取：{source_types}）
- description: 说明为什么需要这个参考
- target_categories: 服务的功能分类（从以下选取：{category_ids}）
- search_queries: 搜索查询词（至少3个，同时包含现实参考和美术设计参考）
- negative_queries: 负向过滤词
- expected_visual_features: 预期视觉特征
- relation_to_setting: 与整体设定的关系

要求：
1. 每个 track 应该是可搜索的实际内容或明确视觉方向。
2. 不要生成过于抽象、无法搜索的 track。
3. 每个 track 至少给出 3 个搜索查询。
4. 查询词要同时包含现实参考查询和美术设计查询。
5. 输出严格 JSON 数组。

设定解析结果：
{setting_parse_json}"""


SOURCE_TYPES_STR = ", ".join([
    "real_world_location", "real_world_object", "architecture_style",
    "historical_period", "cultural_reference", "religious_reference",
    "game_reference", "film_reference", "concept_art_reference",
    "material_reference", "costume_reference", "environment_reference",
    "color_lighting_reference", "composition_reference", "anti_reference",
])

CATEGORY_IDS_STR = ", ".join(CATEGORY_IDS)


def plan_references(
    parse_result: SettingParseResult,
    setting_text: str = "",
    api_base: str = DEFAULT_API_BASE,
    model: str = "",
    api_key: str = "",
) -> list[ReferenceTrack]:
    """Generate Reference Tracks from a parsed setting."""
    parse_json = json.dumps(parse_result.model_dump(), ensure_ascii=False, indent=2)
    prompt = REFERENCE_PLANNER_PROMPT.format(
        source_types=SOURCE_TYPES_STR,
        category_ids=CATEGORY_IDS_STR,
        setting_parse_json=parse_json,
    )

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
            "temperature": 0.4,
        },
        timeout=180.0,
    )
    resp.raise_for_status()

    content = resp.json()["choices"][0]["message"]["content"]
    tracks_data = _parse_json_response(content)

    if not isinstance(tracks_data, list):
        tracks_data = tracks_data.get("reference_tracks", tracks_data.get("tracks", []))

    tracks = []
    for t in tracks_data:
        track = ReferenceTrack(
            id=f"track_{uuid.uuid4().hex[:8]}",
            name=t.get("name", "未命名"),
            description=t.get("description", ""),
            source_type=t.get("source_type", "real_world_reference"),
            target_categories=t.get("target_categories", []),
            search_queries=t.get("search_queries", []),
            negative_queries=t.get("negative_queries", [
                "cartoon", "anime", "logo", "product", "meme",
            ]),
            expected_visual_features=t.get("expected_visual_features", []),
            relation_to_setting=t.get("relation_to_setting", ""),
        )
        tracks.append(track)

    return tracks


def _parse_json_response(content: str) -> list[dict]:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\[[\s\S]*\]", cleaned)
        if match:
            return json.loads(match.group())
        return []
