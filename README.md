# Art Reference Collector

美术参考图片收集工具。搜索、下载、去重、多维视觉分析、结构化画板编排、无限画布画廊展示。

## 前置条件

### 必需

- **Python >= 3.12**
- **[uv](https://docs.astral.sh/uv/)** 包管理器

### Cherry Studio（VLM 分析必需）

视觉分析（图片标注、评选评分、Board 分析）需要通过 Cherry Studio 的 API Server 调用视觉语言模型。

**安装与配置**：

1. 下载安装 [Cherry Studio](https://cherry-ai.com/)
2. 在设置中配置至少一个视觉模型的 API 密钥（支持 OpenAI / Anthropic / Google / 智谱等）
3. 在设置中启用 **API Server**（设置 → API Server → 开启）
4. 默认监听地址：`http://localhost:23333`

**模型配置**：

默认模型为 `zhipu:glm-4.6v`（智谱 GLM-4.6V）。可通过 `--model` 参数切换：

```bash
# 使用不同模型
uv run python run.py analyze-board --board <id> --model openai:gpt-4o
uv run python run.py analyze-board --board <id> --model anthropic:claude-sonnet-4
uv run python run.py analyze-board --board <id> --model google:gemini-2.5-pro
```

模型格式为 `provider:model`，需与 Cherry Studio 中已配置的 provider 和模型名称一致。

**不需要 Cherry Studio 的步骤**：
- 搜索、下载、去重、像素指标计算、存储、画廊生成 — 均可离线运行
- 画廊查看器查看已有 Board — 完全离线

---

## 工作流

### Collection 流程（旧版，快速收集）

```
search → download → dedup → metrics → store → gallery
```

### Board 流程（新版，结构化参考板）

```
search → download → dedup → store --board
                                   ↓
                        parse（设定解析）→ plan（搜索规划）
                                   ↓
                    analyze-board → rank → compose
```

---

## Collection 工作流

### 1. 搜索

```bash
uv run python run.py search "<关键词>" --max 30
```

可选参数：
- `--type photo | clipart | transparent | line`
- `--size Small | Medium | Large | Wallpaper`
- `--layout Square | Tall | Wide`

返回 `session_id`，后续步骤需要它。

### 2. 下载

```bash
uv run python run.py download --session <session_id>
```

### 3. 去重

```bash
uv run python run.py dedup --session <session_id> [--clip] [--threshold 0.92]
```

- 默认使用感知哈希（pHash）去重
- 加 `--clip` 启用 CLIP 语义去重（首次需下载约 600MB 模型）

### 4. 指标分析

```bash
# 像素指标（无需 API）
uv run python run.py metrics --session <session_id>

# 同时启用 VLM 主观指标
uv run python run.py metrics --session <session_id> --vlm
```

### 5. 存储

```bash
uv run python run.py store --session <session_id> --topic "<主题名>"
```

### 6. 画廊配置

```bash
uv run python run.py gallery --topic "<主题名>"
```

### 一键流水线

```bash
uv run python run.py pipeline "<关键词>" --max 30 --topic <主题名>
```

---

## Board 工作流

Board 是结构化的美术参考板，支持设定文本、搜索规划、功能分类、评分排序和分区编排。

### 1. 导入到 Board

```bash
uv run python run.py store --session <session_id> --board "<board_id>"
```

Board ID 同时用作文件夹名，建议使用可读名称如 `S3_屏蔽室`。

### 2. 设定解析

```bash
uv run python run.py parse --board <board_id>
```

输入设定文本（游戏场景描述等），自动解析为结构化的视觉目标和风格要求。

### 3. 搜索规划

```bash
uv run python run.py plan --board <board_id>
```

根据设定生成多条搜索轨道（Reference Track），每条轨道包含关键词和目标图片数。

### 4. Board 图片分析

```bash
uv run python run.py analyze-board --board <board_id>
```

对每张图片进行 Board 上下文感知分析，生成：
- 相关性和推荐度评分
- 8 维评选分数（美观度、构图、光照、设计参考度等）
- 功能分类建议（建筑、氛围、材质等）
- 视觉指标（15 维，含像素计算 + VLM 感知维度）

### 5. 排序

```bash
uv run python run.py rank --board <board_id>
```

三阶段去重（SHA256 → pHash → CLIP）+ 加权评分 + 状态分级。

评分权重（可在 config.py 中修改）：

| 权重 | 默认值 | 含义 |
|------|--------|------|
| relevance | 0.18 | 与设定的相关性 |
| design_reference | 0.16 | 设计参考价值 |
| aesthetic | 0.14 | 美观度 |
| style_consistency | 0.14 | 风格一致性 |
| composition | 0.10 | 构图质量 |
| lighting | 0.10 | 光照质量 |
| usability | 0.08 | 可用性 |
| uniqueness | 0.06 | 独特性 |
| source_quality | 0.04 | 来源质量 |
| risk_penalty | 0.08 | 风险惩罚（减分） |
| duplicate_penalty | 0.10 | 重复惩罚（减分） |

状态分级：

| 分级 | 条件 |
|------|------|
| 核心 | 综合分 ≥ 0.82 且 风格一致 ≥ 0.70 |
| 精选 | 综合分 ≥ 0.68 |
| 补充 | 综合分 ≥ 0.50 |
| 异常 | 风格一致 ≤ 0.40 且 相关性 ≥ 0.60 |
| 排除 | 相关性 < 0.45 或 设计参考 < 0.35 |

### 6. 画板编排

```bash
uv run python run.py compose --board <board_id> [--model <provider:model>]
```

将图片按功能分类组织为分区画板，可选启用 VLM 生成分区摘要。

### 7. 本地 API Server（可选）

```bash
uv run python run.py serve --port 8765
```

提供 REST API 用于前端写回操作（排序保存等）。查看 Board 不需要启动服务器。

---

## 画廊查看器

### 使用

直接在浏览器中打开 `gallery/canvas.html`（支持 `file://` 协议，无需 HTTP 服务器）。

### 加载 Board

1. 点击左侧 **Load Board**
2. 选择 Board 文件夹（如 `data/boards/S3_屏蔽室/`）
3. 所有图片通过本地文件加载，无需服务器

### 视图模式

| 模式 | 说明 |
|------|------|
| Board | 分区画板视图，按功能分类展示，支持拖拽排序 |
| Grid | 平铺网格，所有图片一览 |
| Scatter | 散点图，按任意两维指标分布 |

### 工具栏面板

| 面板 | 说明 |
|------|------|
| Axes | 散点图轴选择（视觉指标 / 感知维度 / 评选分数） |
| Map | 小地图导航 |
| Info | Board 信息面板（名称、视觉目标、设定文本、统计） |
| Score | 评分权重调整面板，可实时修改权重并重算分级 |

### 图片分级

每张图片左上角显示分级标签：
- **核心**（红）— 高分高一致性的核心参考
- **精选**（绿）— 优质精选参考
- **补充**（蓝）— 补充性参考
- **异常**（黄）— 相关但风格偏离
- **待审**（灰）— 尚未分析
- **排除**（暗）— 不相关或低质量

点击图片可查看详情：分级标签 + 完整评分权重分解（每个子分的值 × 权重 = 贡献值）。

### 快捷操作

| 操作 | 方式 |
|------|------|
| 平移 | 鼠标拖拽 |
| 缩放 | 鼠标滚轮 |
| 居中适配 | 工具栏 Fit 按钮 |
| 切换布局 | Grid / Scatter / Board 按钮 |
| 小地图 | Map 按钮 |

---

## 视觉指标

### 像素指标（自动计算）

| 指标 | 轴向 | 说明 |
|------|------|------|
| brightness | 暗 ↔ 亮 | 平均亮度 |
| saturation | 灰 ↔ 鲜艳 | HSV 饱和度 |
| warmth | 冷 ↔ 暖 | 色温倾向 |
| contrast | 柔和 ↔ 强对比 | 亮度对比度 |
| color_complexity | 单纯 ↔ 丰富 | 色彩丰富度 |
| detail_density | 简洁 ↔ 复杂 | 细节密度 |
| openness | 封闭 ↔ 开阔 | 空间开阔度 |

### 感知维度（VLM 评分）

| 指标 | 轴向 |
|------|------|
| shot_scale | 远景 ↔ 特写 |
| monumentality | 私密 ↔ 宏大 |
| religiousness | 弱 ↔ 强 |
| industrialness | 弱 ↔ 强 |
| decay | 完整 ↔ 破败 |
| orderliness | 混乱 ↔ 规整 |
| fantasy_level | 现实 ↔ 奇幻 |
| sci_fi_level | 现实 ↔ 科幻 |

### 评选分数（VLM 评分）

| 指标 | 说明 |
|------|------|
| aesthetic_score | 美观度 |
| composition_score | 构图质量 |
| lighting_score | 光照质量 |
| design_reference_score | 设计参考价值 |
| style_consistency_score | 风格一致性 |
| uniqueness_score | 独特性 |
| usability_score | 可用性 |
| risk_score | 风险度 |

---

## 数据目录

```
art-ref-collector/
├── data/
│   ├── boards/<board_id>/    # Board 数据（自包含文件夹）
│   │   ├── _board.json       # Board 完整数据（图片/分区/分数）
│   │   ├── images/           # 原图
│   │   └── thumbnails/       # 缩略图
│   ├── images/<topic>/       # Collection 图片（旧版）
│   ├── metrics/<session>/    # 每张图片的指标 JSON
│   ├── sessions/             # 搜索/下载会话数据
│   └── art_ref.db            # SQLite 元数据库
├── gallery/
│   └── canvas.html           # 画布查看器（支持 file:// 直接打开）
├── run.py                    # CLI 入口
└── config.py                 # 配置
```
