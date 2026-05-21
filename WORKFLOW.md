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

---

### Step 5: parse — 设定解析

```bash
uv run python run.py parse --board <board_id>
```

**做什么**：通过 LLM 将自由文本的场景设定解析为结构化的视觉需求。需要 Cherry Studio。

**输入**：交互式输入设定文本（如 "S3 屏蔽室是一个废弃的地下屏蔽室..."）。

**产出**：
- `visual_goal_summary`：视觉目标摘要（一句话概括视觉方向）
- `setting_text`：原始设定文本（保存备查）
- `style_profile`：结构化风格要求（色彩、构图、建筑、氛围等维度）

**示例设定文本**：
> S3 屏蔽室是一个位于地下的废弃屏蔽室，内部空间狭长，混凝土墙面斑驳，
> 有工业管道和金属栏杆。氛围压抑、神秘，有科幻感。冷色调为主，
> 偶有荧光灯的暖光点缀。

---

### Step 6: plan — 搜索规划

```bash
uv run python run.py plan --board <board_id>
```

**做什么**：根据设定的视觉目标和风格要求，通过 LLM 生成多条搜索轨道（Reference Track）。需要 Cherry Studio。

每条搜索轨道包含：
- 搜索关键词（英文）
- 目标图片数量
- 搜索目的说明（如 "寻找混凝土建筑内部参考"）

**产出**：在 Board 数据中创建 Reference Track 记录。

**示例产出**：
| Track | 关键词 | 数量 | 目的 |
|-------|--------|------|------|
| T1 | brutalist concrete corridor interior | 8 | 混凝土走廊内部 |
| T2 | industrial tunnel fluorescent lighting | 6 | 工业隧道荧光灯 |
| T3 | abandoned bunker sci-fi | 5 | 废弃掩体科幻感 |

---

### Step 7: analyze-board — Board 图片分析

```bash
uv run python run.py analyze-board --board <board_id>
```

**做什么**：对 Board 中的每张图片进行深度视觉分析。需要 Cherry Studio。

这是最核心的分析步骤，一次调用完成：

1. **视觉指标**（15 维）：
   - 像素计算：brightness, saturation, warmth, contrast, color_complexity, detail_density
   - VLM 评分：shot_scale, openness, monumentality, religiousness, industrialness, decay, orderliness, fantasy_level, sci_fi_level

2. **评选分数**（8 维）：aesthetic_score, composition_score, lighting_score, design_reference_score, style_consistency_score, uniqueness_score, usability_score, risk_score

3. **相关性分析**：
   - 与设定文本的相关性评分（0-1）
   - 是否推荐作为参考（推荐/核心/补充/排除）
   - 推荐的功能分类（建筑、氛围、材质等）

4. **文字描述**：
   - 视觉摘要
   - 可用元素列表
   - 风格标签
   - 风险提示

**产出**：每张图片的 `visual_metrics`、`curation_scores`、`analysis` 写入数据库。

---

### Step 8: rank — 排序分级

```bash
uv run python run.py rank --board <board_id>
```

**做什么**：三阶段去重 + 加权评分 + 自动分级。不需要 Cherry Studio。

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
