# Art Reference Collector

美术参考图片收集工具。搜索、下载、去重、多维视觉分析、无限画布画廊展示。

## 工作流

完整流水线分步执行，每一步的结果供下一步使用：

```
search → download → dedup → metrics → store → gallery
```

### 1. 搜索

```bash
uv run python run.py search "<关键词>" --max 30
```

可选参数：
- `--type photo | clipart | transparent | line`
- `--size Small | Medium | Large | Wallpaper`
- `--layout Square | Tall | Wide`
- `--region wt-wt`（默认全球）

返回 `session_id`，后续步骤都需要它。

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
uv run python run.py metrics --session <session_id> --vlm --api-key <your_key>
```

**像素指标**（自动计算，无需外部 API）：

| 指标 | 轴向含义 | 计算方式 |
|------|---------|---------|
| brightness | 暗 ↔ 亮 | 平均亮度 / 255 |
| saturation | 灰 ↔ 鲜艳 | HSV 平均饱和度 / 255 |
| color_temperature | 冷 ↔ 暖 | 暖色像素占比 |
| dominant_hue | 蓝绿 ↔ 红黄 | 圆形均值色相 |
| contrast | 柔和 ↔ 强对比 | 亮度标准差 / 128 |
| color_complexity | 单纯 ↔ 丰富 | 色相直方图熵 |
| edge_density | 简洁 ↔ 复杂 | Sobel 梯度像素比 |
| texture_complexity | 平滑 ↔ 粗糙 | Laplacian 方差 |
| composition_x | 左 ↔ 右 | 梯度质心 X |
| composition_y | 上 ↔ 下 | 梯度质心 Y |
| spatial_openness | 封闭 ↔ 开阔 | 上部低梯度区占比 |

**主观指标**（VLM 评分，需启用 `--vlm`）：

| 指标 | 轴向含义 |
|------|---------|
| shot_scale | 远景 ↔ 特写 |
| spatial_scale | 私密 ↔ 宏大 |
| emotion_intensity | 平静 ↔ 紧张 |
| oppression | 开放 ↔ 压迫 |
| industrialness | 弱 ↔ 强 |
| fantasy_level | 现实 ↔ 奇幻 |
| decay_level | 完整 ↔ 破败 |
| ornateness | 朴素 ↔ 华丽 |
| era_feel | 古典 ↔ 未来 |
| reference_value | 弱参考 ↔ 强参考 |
| ... 等 14 个维度 |

### 5. 存储

```bash
uv run python run.py store --session <session_id> --topic "<主题名>"
```

将图片整理到 `data/images/<主题名>/` 并写入 SQLite 数据库。

### 6. 画廊配置

```bash
uv run python run.py gallery --topic "<主题名>"
# 或批量生成
uv run python run.py gallery --topic "S3_屏蔽室" "S1_焰砂海矿营" "S7_冠脊林活矿林"
```

在每个主题的图片文件夹内生成 `_collection.json`，内含图片列表和嵌入的指标数据。

### 一键流水线

```bash
uv run python run.py pipeline "<关键词>" --max 30 --topic <主题名>
```

自动执行搜索 → 下载 → 去重 → 存储 → 画廊生成的完整流程。

## 画廊查看器

### 启动

```bash
python -m http.server 8000
```

浏览器打开 `http://localhost:8000/gallery/canvas.html`。

### 使用方法

1. **导入 Collection**：点击左侧 Nav 面板的「+ Import Folder」，选择包含 `_collection.json` 的图片文件夹
2. **隐藏/显示**：点击 Collection 名称或色点切换可见性
3. **移除**：点击 × 按钮卸载 Collection
4. **浏览**：鼠标拖拽平移，滚轮缩放（以鼠标位置为中心）
5. **Scatter 模式**：点击底部工具栏 Scatter 按钮，切换为散点图布局
6. **双轴选择**：开启 Scatter 模式后，点击工具栏 Axes 按钮，在右侧面板选择 X/Y 轴指标
7. **查看详情**：点击任意图片打开详情弹窗，显示指标条形图

### 快捷操作

| 操作 | 方式 |
|------|------|
| 平移 | 鼠标拖拽 |
| 缩放 | 鼠标滚轮 |
| 居中适配 | 工具栏 Fit 按钮 |
| 放大/缩小 | 工具栏 +/- 按钮 |
| 切换布局 | Grid / Scatter 按钮 |
| 小地图 | Map 按钮 |

## 数据目录

```
art-ref-collector/
├── data/
│   ├── images/<topic>/     # 按主题组织的图片 + _collection.json
│   ├── metrics/<session>/  # 每张图片的指标 JSON
│   ├── sessions/           # 搜索/下载会话数据
│   ├── galleries/          # 旧版 HTML 画廊（可选）
│   └── art_ref.db          # SQLite 元数据库
├── gallery/
│   └── canvas.html         # 无限画布查看器
├── run.py                  # CLI 入口
└── config.py               # 配置
```

## 前置条件

- Python >= 3.12
- [uv](https://docs.astral.sh/uv/) 包管理器
- 可选：Cherry Studio API Server（用于 VLM 主观指标分析）
