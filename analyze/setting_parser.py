"""Setting Parser — extract structured visual requirements from text settings."""

import json
import re
import sys

import httpx

from config import DEFAULT_API_BASE
from models.schemas import SettingParseResult, StyleProfile


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
        # Try to find JSON object in the response
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if match:
            return json.loads(match.group())
        return {}
