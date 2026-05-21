# 工作流指南

本文档详细说明 Art Reference Collector 的两种工作流及其每一步的执行内容和产出。

---

## 快速参考

### Collection 工作流（快速收集 + 浏览）

适合：快速搜索关键词、收集参考图、在画布中浏览。

```
search → download → dedup → metrics → store → gallery
```

### Board 工作流（结构化参考板）

适合：围绕一个具体场景/设定，系统性地收集、分析、编排美术参考。

```
search → download → dedup → store --board
                                   ↓
                        parse → plan → analyze-board → rank → compose
```

---

## 前置准备

### 1. 安装依赖

```bash
# 需要 Python >= 3.12 和 uv 包管理器
cd art-ref-collector
uv sync    # 首次运行自动安装依赖（含 PyTorch + CLIP，约 2.6GB）
```

### 2. Cherry Studio（VLM 分析必需）

视觉分析步骤需要 Cherry Studio 提供 API 服务：

1. 安装 [Cherry Studio](https://cherry-ai.com/)
2. 在设置中配置视觉模型的 API 密钥（支持 OpenAI / Anthropic / 智谱等）
3. 启用 **API Server**（设置 → API Server → 开启）
4. 默认监听 `http://localhost:23333`

以下步骤**不需要** Cherry Studio：
- search / download / dedup / metrics（仅像素指标）/ store / gallery
- 画廊查看器查看已有 Board

---

## 步骤详解

### Step 1: search — 搜索图片

```bash
uv run python run.py search "<关键词>" --max 30
```

**做什么**：通过 Bing 图片搜索 API 搜索指定关键词的图片，获取图片 URL、缩略图和元数据。

**参数**：
- `--max`：最大搜索数量（默认 30）
- `--type`：图片类型 — `photo` / `clipart` / `transparent` / `line`
- `--size`：尺寸 — `Small` / `Medium` / `Large` / `Wallpaper`
- `--layout`：布局 — `Square` / `Tall` / `Wide`

**产出**：创建搜索会话，保存到 `data/sessions/<session_id>.json`，包含每张图片的 URL、标题、来源等信息。

**依赖**：
- `duckduckgo-search` — Bing 图片搜索（主力）
- `httpx` — HTTP 客户端（用于 SearXNG 备用搜索引擎）
- 备用方案：自建 [SearXNG](https://github.com/searxng/searxng) 实例，通过 `config.py` 配置

**提示**：
- 使用英文关键词效果更好
- 可以用 `--type photo` 过滤照片类结果
- 可以多次搜索不同关键词，后续步骤按 session_id 分别处理

---

### Step 2: download — 下载图片

```bash
uv run python run.py download --session <session_id>
```

**做什么**：将搜索会话中的图片 URL 批量下载到本地，计算 SHA256 和 pHash。

**产出**：图片文件保存到 `data/sessions/<session_id>/` 目录。每张图片生成缩略图。

**依赖**：
- `httpx` — 异步 HTTP 下载（主力）
- `Pillow` — 缩略图生成
- 备用方案：`gallery-dl`（站点专用下载）、`img2dataset`（批量重试）

---

### Step 3: dedup — 去重

```bash
uv run python run.py dedup --session <session_id> [--clip] [--threshold 0.92]
```

**做什么**：三阶段去重，去除重复或高度相似的图片：

1. **SHA256 精确去重**：删除完全相同的文件
2. **pHash 感知哈希去重**：基于图片结构相似性，汉明距离 < 阈值的视为重复
3. **CLIP 语义去重**（需加 `--clip`）：基于视觉语义相似度，捕捉内容相似但像素不同的图片

**参数**：
- `--clip`：启用 CLIP 语义去重（首次需下载约 600MB 模型）
- `--threshold`：CLIP 相似度阈值（默认 0.92，越高越严格）

**产出**：在会话数据中标记重复图片，不删除文件。

**依赖**：
- `hashlib`（stdlib）— SHA256 精确去重
- `imagehash` + `Pillow` — pHash 感知哈希去重
- `open-clip-torch` + `torch`（~2.6GB）— CLIP 语义去重（可选，加 `--clip` 启用）
- 备用方案：仅使用 pHash（不加 `--clip`），精度稍低但无需下载大模型

---

### Step 4: store — 存储入库

#### Collection 模式

```bash
uv run python run.py store --session <session_id> --topic "<主题名>"
```

**做什么**：将图片整理到 `data/images/<主题名>/` 目录，写入 SQLite 数据库。

**产出**：`data/images/<主题名>/` 目录含图片文件。

#### Board 模式

```bash
uv run python run.py store --session <session_id> --board "<board_id>"
```

**做什么**：将图片导入到 Board 系统，创建 Board 文件夹结构。

**产出**：
- `data/boards/<board_id>/images/` — 原图
- `data/boards/<board_id>/thumbnails/` — 缩略图
- SQLite 数据库中创建 Board 和图片记录

**提示**：Board ID 建议使用可读名称如 `S3_屏蔽室`、`角色_机甲设计`。

**依赖**：
- `sqlite3`（stdlib）— 元数据库
- `pydantic` — 数据模型校验
- `Pillow` — 缩略图生成（Board 模式）
- `faiss-cpu` — 向量索引（主用）
- 备用方案：`lancedb`（替代向量后端，通过 `config.py` 切换）

---

### Step 5: parse — 设定解析

```bash
# 方式一：交互式输入
uv run python run.py parse --board <board_id>

# 方式二：从文件读取
uv run python run.py parse --board <board_id> --file setting.txt

# 方式三：直接传入
uv run python run.py parse --board <board_id> --setting "场景设定文本..."

# 指定 Board 名称（不指定则取设定文本前 30 字符）
uv run python run.py parse --board <board_id> --name "S3 屏蔽室" --file setting.txt
```

**做什么**：将自由文本的场景设定通过 LLM 解析为结构化视觉需求。需要 Cherry Studio。

**依赖**：
- `httpx` — 调用 Cherry Studio API Server（OpenAI 兼容接口）
- `pydantic` — 解析结果结构化（`SettingParseResult`, `StyleProfile`）
- LLM 模型：通过 Cherry Studio 调用，默认 `zhipu:glm-4.6v`

**LLM 的工作**：调用 `analyze/setting_parser.py`，将设定文本发给 LLM，要求其输出结构化 JSON：

1. **`core_concepts`** — 核心视觉概念（英文关键词，可直接用于搜索）
   - 从设定文本中提取关键视觉元素，翻译为英文搜索词
   - 例如："混凝土走廊" → `brutalist concrete corridor`

2. **`visual_dimensions`** — 涉及的功能维度，从以下分类中选取：
   - mood（氛围）、architecture（建筑）、interior（室内）、materials（材质）
   - color_lighting（色彩光照）、composition（构图）、props（道具）
   - costume_character（角色）、tech_machinery（机械）、landscape（自然）等

3. **`known_references`** — 设定中**明确提到**的参考来源
   - 例如："参考 Control 的 Brutalist 风格" → `Control game brutalist architecture`

4. **`implicit_references`** — 设定中**隐含但未明说**的参考来源
   - 例如："地下掩体、压抑氛围" → 隐含参考切尔诺贝利、核掩体等

5. **`missing_references`** — 设定中**缺失但需要**的参考
   - 例如：设定描述了建筑但没提家具 → 缺少室内道具参考

6. **`style_profile`** — 各维度的风格标签：
   - `mood`：氛围关键词（如 oppressive, mysterious, sterile）
   - `architecture`：建筑风格（如 brutalist, industrial, sci-fi）
   - `color`：色彩方向（如 cold blue-gray, fluorescent accent）
   - `materials`：材质关键词（如 concrete, rusted metal, peeling paint）
   - `lighting`：光照风格（如 harsh fluorescent, volumetric fog）
   - `composition`：构图偏好（如 claustrophobic framing, vanishing point）
   - `avoid`：应避免的方向（如 anime, cartoon, bright colors）

7. **`clarification_questions`** — 需要用户进一步澄清的问题

**产出**：
- `data/boards/<board_id>/parse_result.json` — 完整解析结果
- Board 数据中保存 `visual_goal_summary`、`setting_text`、`style_profile`

**示例**：

输入设定：
> S3 屏蔽室是一个位于地下的废弃屏蔽室，内部空间狭长，混凝土墙面斑驳，
> 有工业管道和金属栏杆。氛围压抑、神秘，有科幻感。冷色调为主，
> 偶有荧光灯的暖光点缀。

解析产出（节选）：
```json
{
  "core_concepts": ["underground bunker", "concrete interior", "industrial corridor", "sci-fi bunker"],
  "known_references": [],
  "implicit_references": ["Chernobyl control room", "nuclear bunker", "Stranger Things lab"],
  "missing_references": ["emergency signage", "ventilation systems", "blast doors"],
  "style_profile": {
    "mood": ["oppressive", "mysterious", "sterile", "abandoned"],
    "architecture": ["brutalist", "utilitarian", "underground"],
    "color": ["cold blue-gray", "concrete", "fluorescent warm accent"],
    "materials": ["raw concrete", "rusted metal", "peeling paint"],
    "lighting": ["harsh fluorescent", "volumetric dust"],
    "composition": ["claustrophobic", "vanishing point corridor"],
    "avoid": ["bright colors", "fantasy", "clean pristine"]
  },
  "clarification_questions": [
    "这个空间是否仍在使用中还是完全废弃？",
    "是否有科幻元素（如全息屏幕、能量管道）？"
  ]
}
```

---

### Step 6: plan — 搜索规划

```bash
uv run python run.py plan --board <board_id>
```

**做什么**：根据 parse 步骤的结构化视觉需求，通过 LLM 生成多条搜索轨道（Reference Track）。需要 Cherry Studio。

**依赖**：
- `httpx` — 调用 Cherry Studio API Server
- `pydantic` — 轨道数据结构化（`ReferenceTrack`）
- LLM 模型：通过 Cherry Studio 调用

**LLM 的工作**：调用 `analyze/reference_planner.py`，将 parse 结果发给 LLM，要求其生成可执行的搜索计划。

每条搜索轨道包含以下字段：

| 字段 | 说明 | 示例 |
|------|------|------|
| `name` | 参考线索名称 | "混凝土走廊内部" |
| `source_type` | 来源类型 | `architecture_style` / `real_world_location` / `concept_art_reference` 等 |
| `description` | 为什么需要这个参考 | "核心空间参考，决定玩家第一印象" |
| `target_categories` | 服务的功能分类 | `["interior", "architecture"]` |
| `search_queries` | 搜索查询词（≥3个） | 见下方 |
| `negative_queries` | 负向过滤词 | `["cartoon", "anime", "logo"]` |
| `expected_visual_features` | 预期视觉特征 | `["long corridor", "concrete walls", "fluorescent lights"]` |
| `relation_to_setting` | 与设定的关系 | "直接对应S3的核心空间" |

**搜索查询词的设计**：

每个 track 会生成至少 3 个查询词，覆盖两类参考：

1. **现实参考查询**（real world reference）：
   - 寻找真实世界中存在的对应场景照片
   - 例如：`abandoned nuclear bunker interior photo`、`brutalist concrete corridor photography`

2. **美术设计查询**（concept art reference）：
   - 寻找游戏/电影/概念美术中的类似设计
   - 例如：`sci-fi bunker concept art`、`underground facility game art`

**负向过滤词**：

每条轨道自带默认的排除词：`cartoon, anime, logo, product, meme, low resolution, stock photo, watermark, toy`。LLM 可根据具体需求添加额外的排除词（如 `bright colors, clean, modern office`）。

**产出**：
- `data/boards/<board_id>/reference_tracks.json` — 所有搜索轨道
- Board 数据中保存 `reference_tracks`

**示例产出**：
```json
[
  {
    "name": "混凝土走廊空间",
    "source_type": "architecture_style",
    "search_queries": [
      "brutalist concrete corridor interior photography",
      "underground bunker tunnel fluorescent lights",
      "sci-fi facility corridor concept art"
    ],
    "negative_queries": ["cartoon", "anime", "clean office", "bright"],
    "target_categories": ["interior", "architecture"],
    "expected_visual_features": ["long corridor", "concrete walls", "fluorescent lights", "industrial details"]
  },
  {
    "name": "工业细节与管道",
    "source_type": "real_world_object",
    "search_queries": [
      "industrial pipes metal railings abandoned",
      "factory ventilation ducts rusted texture",
      "power plant machinery detail reference"
    ],
    "negative_queries": ["cartoon", "modern", "clean"],
    "target_categories": ["materials", "tech_machinery"],
    "expected_visual_features": ["metal pipes", "gratings", "cables", "rust textures"]
  }
]
```

---

### 搜索与迭代

plan 步骤产出的每条搜索轨道包含多个 `search_queries`，用户需要使用这些查询词执行搜索：

```bash
# 对每条轨道的每个查询词执行搜索
uv run python run.py search "brutalist concrete corridor interior photography" --max 10 --type photo
uv run python run.py search "underground bunker tunnel fluorescent lights" --max 10 --type photo
uv run python run.py search "sci-fi facility corridor concept art" --max 10 --type photo

# 下载、去重、导入
uv run python run.py download --session <session_1>
uv run python run.py download --session <session_2>
uv run python run.py download --session <session_3>
uv run python run.py dedup --session <session_1> --clip
uv run python run.py dedup --session <session_2> --clip
uv run python run.py dedup --session <session_3> --clip
uv run python run.py store --session <session_1> --board "S3_屏蔽室"
uv run python run.py store --session <session_2> --board "S3_屏蔽室"
uv run python run.py store --session <session_3> --board "S3_屏蔽室"
```

**搜索技巧**：
- 使用英文关键词效果最好（plan 生成的查询词已经是英文）
- `--type photo` 过滤照片类结果，`--type clipart` 适合找插图类参考
- `--layout Wide` 适合找宽幅场景，`--layout Tall` 适合找竖构图
- 如果某个查询词结果不理想，可以微调关键词后重新搜索
- 多条轨道的结果可以合并到同一个 Board

**迭代流程**：完成一轮搜索 → analyze-board → rank → compose 后，compose 步骤会输出 `missing_needs`（缺失的参考方向）和 `next_search_suggestions`（下一轮搜索建议）。根据这些建议回到搜索步骤补充图片。

---

### Step 7: analyze-board — Board 图片分析（搜索结果筛选）

```bash
uv run python run.py analyze-board --board <board_id>
```

**做什么**：对 Board 中的每张图片进行深度视觉分析，**这是搜索结果的自动筛选机制**。需要 Cherry Studio。

搜索步骤导入的图片是未经筛选的原始结果。analyze-board 通过 VLM 对每张图片进行上下文感知分析，自动判断图片是否与 Board 的设定相关、质量如何、适合作为哪种参考。

**分析过程**（每张图片调用一次 VLM，传入图片 + Board 设定文本 + 风格要求）：

1. **相关性评估**：
   - `relevance_score`（0-1）：与设定文本的视觉相关程度
   - `is_relevant`（bool）：是否推荐保留
   - `final_recommendation`：`core` / `reference` / `supplement` / `reject`

2. **评选分数**（8 维，均为 0-1）：
   - `design_reference_score`：作为设计参考的价值
   - `aesthetic_score`：美观程度
   - `composition_score`：构图质量
   - `lighting_score`：光照质量
   - `style_consistency_score`：与设定风格的一致性
   - `uniqueness_score`：独特性（避免千篇一律）
   - `usability_score`：可操作性（能否直接用于设计）
   - `risk_score`：风险度（是否可能引入不想要的方向）

3. **视觉指标**（15 维）：
   - 像素自动计算：brightness, saturation, warmth, contrast, color_complexity, detail_density
   - VLM 评分：shot_scale, openness, monumentality, religiousness, industrialness, decay, orderliness, fantasy_level, sci_fi_level

4. **功能分类建议**：
   - 根据图片内容自动分配到功能分类（建筑/氛围/材质/色彩/构图等）
   - 每个分类带置信度分数

5. **文字描述**：视觉摘要、可用元素、风格标签、风险提示

**筛选如何生效**：analyze-board 的产出供下一步 rank 使用。rank 步骤根据 `relevance_score` 和 `design_reference_score` 的阈值自动排除不相关图片，根据综合评分自动分级（核心/精选/补充/排除）。用户无需手动筛选每张图片。

**参数**：
- `--status`：只分析指定状态的图片（默认 `candidate`，即只分析未分析过的）

**产出**：每张图片的 `visual_metrics`、`curation_scores`、`analysis` 写入数据库。

**依赖**：
- `httpx` — 调用 VLM（Cherry Studio API Server）
- `Pillow` + `numpy` + `scipy` — 像素级视觉指标计算（brightness, saturation, warmth 等）
- `pydantic` — 分析结果结构化
- `tqdm` — 进度条

---

### Step 8: rank — 排序分级

```bash
uv run python run.py rank --board <board_id>
```

**做什么**：三阶段去重 + 加权评分 + 自动分级。不需要 Cherry Studio。

**依赖**：
- `hashlib`（stdlib）— SHA256 精确去重
- `imagehash` + `Pillow` — pHash 感知哈希去重
- `open-clip-torch` + `torch` — CLIP 语义去重（可选）
- `numpy` — 分数计算

1. **三阶段去重**：
   - SHA256 精确去重（标记 penalty = 1.0）
   - pHash 感知哈希去重（标记 penalty = 0.85）
   - CLIP 语义去重（标记 penalty = 相似度值）

2. **加权评分**：综合 9 个正向维度和 2 个惩罚维度计算 `final_score`（0-1）：
   ```
   final_score = Σ(权重_i × 分数_i) - Σ(惩罚权重_j × 惩罚值_j)
   ```

3. **自动分级**：按 `final_score` 和关键子分分配状态：
   - **核心**：≥ 0.82 且 风格一致 ≥ 0.70
   - **精选**：≥ 0.68
   - **补充**：≥ 0.50
   - **异常**：风格偏离但相关
   - **排除**：不相关或低质量
   - **重复**：与更优图片高度相似

**产出**：每张图片获得 `final_score` 和 `status`，写入数据库，更新 `_board.json`。

---

### Step 9: compose — 画板编排

```bash
# 基础编排（不需要 Cherry Studio）
uv run python run.py compose --board <board_id>

# 带分区摘要的编排（需要 Cherry Studio）
uv run python run.py compose --board <board_id> --model zhipu:glm-4.6v
```

**做什么**：将图片按功能分类组织为结构化画板。

**依赖**：
- `httpx` — 调用 VLM 生成分区摘要（可选，加 `--model` 启用）
- `pydantic` — 编排数据结构化
- `tqdm` — 进度条

1. **核心参考选取**：从所有图片中选出 top-N 高分图片作为核心参考
2. **功能分区**：将图片分配到 12 个功能分类（建筑、氛围、材质、色彩、构图等）
3. **分区排序**：每个分区内按分数排列，分为 key images 和 supporting images
4. **摘要生成**（可选）：用 VLM 为每个分区生成美术方向说明
5. **缺失分析**：识别缺少参考图片的方向，生成下一轮搜索建议

**产出**：
- `board_composition.json` — 完整编排数据
- `_board.json` — 更新的 Board 数据
- 分区包含 key_images / supporting_images / summary / missing_needs

---

### 其他命令

#### reorder — 调整图片顺序

```bash
uv run python run.py reorder --board <board_id> --section <section_id> --order img1 img2 img3
```

应用在画廊查看器中拖拽调整的图片顺序。

#### serve — 本地 API 服务器

```bash
uv run python run.py serve --port 8765
```

提供 REST API，用于画廊查看器的写回操作。仅调整排序时需要，查看 Board 不需要。

#### pipeline — 一键流水线

```bash
uv run python run.py pipeline "<关键词>" --max 30 --topic <主题名>
```

自动执行 search → download → dedup → store → gallery 完整流程（Collection 模式）。

#### gallery — 生成画廊配置

```bash
uv run python run.py gallery --topic "<主题名>"
```

生成 `_collection.json`（Collection 模式使用的画廊配置文件）。

---

## 完整示例：从零创建一个 Board

假设要为 "S3 屏蔽室" 场景创建美术参考板：

```bash
# 1. 搜索参考图片（多次搜索不同关键词）
uv run python run.py search "brutalist concrete corridor interior" --max 15 --type photo
# 记下 session_id，如 abc123

uv run python run.py search "abandoned bunker fluorescent lighting sci-fi" --max 15 --type photo
# 记下 session_id，如 def456

# 2. 下载
uv run python run.py download --session abc123
uv run python run.py download --session def456

# 3. 去重
uv run python run.py dedup --session abc123 --clip
uv run python run.py dedup --session def456 --clip

# 4. 导入 Board
uv run python run.py store --session abc123 --board "S3_屏蔽室"
uv run python run.py store --session def456 --board "S3_屏蔽室"

# 5. 设定解析（需要 Cherry Studio）
uv run python run.py parse --board "S3_屏蔽室"
# 按提示输入场景设定文本

# 6. 搜索规划（需要 Cherry Studio）
uv run python run.py plan --board "S3_屏蔽室"
# 根据生成的搜索轨道，回到 Step 1 搜索更多图片

# 7. Board 分析（需要 Cherry Studio）
uv run python run.py analyze-board --board "S3_屏蔽室"

# 8. 排序分级
uv run python run.py rank --board "S3_屏蔽室"

# 9. 画板编排
uv run python run.py compose --board "S3_屏蔽室"

# 10. 查看结果
# 浏览器打开 gallery/canvas.html → Load Board → 选择 data/boards/S3_屏蔽室/
```

---

## 画廊查看器

浏览器直接打开 `gallery/canvas.html`，无需 HTTP 服务器。

### 加载 Board

1. 点击 **Load Board**
2. 选择 Board 文件夹（如 `data/boards/S3_屏蔽室/`）
3. 所有图片从本地文件加载，完全离线

### 视图模式

- **Board**：分区画板，按功能分类展示，支持拖拽排序
- **Grid**：平铺网格，所有图片一览
- **Scatter**：散点图，按任意两维指标分布

### 工具面板

- **Axes**：散点图轴选择
- **Map**：小地图导航
- **Info**：Board 信息（设定文本、视觉目标、统计）
- **Score**：评分权重调整（slider 实时调整，Recompute 即时重算分级）

### 图片分级

每张图片左上角显示分级标签，点击查看详情：
- 核心参考（红）、精选参考（绿）、补充参考（蓝）
- 异常值（黄）、待审（灰）、排除（暗）、重复（暗）

Detail 视图显示完整的评分权重分解：每个子分数 × 权重 = 对最终分数的贡献值。

### 排序调整

在 Board 视图中可拖拽图片调整顺序，点击 **Apply Order** 保存。需要启动 serve 服务用于写回；未启动时会下载 JSON 文件供手动应用。
