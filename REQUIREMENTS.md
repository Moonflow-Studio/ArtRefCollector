# Agent Requirements

Agent 自动运行时的依赖清单和注意事项。

## 系统要求

- Python >= 3.12
- [uv](https://docs.astral.sh/uv/) 包管理器
- 磁盘空间 >= 3GB（首次安装 PyTorch + CLIP 模型）

## Python 依赖

由 `pyproject.toml` 声明，`uv sync` 自动安装。完整列表：

| 包 | 用途 | 磁盘占用 |
|----|------|---------|
| duckduckgo-search | DuckDuckGo 图片搜索 | ~1MB |
| httpx | HTTP 客户端（下载 + API 调用） | ~2MB |
| pillow | 图片读取和缩略图 | ~15MB |
| imagehash | 感知哈希去重 | ~1MB |
| numpy | 像素指标数组计算 | ~30MB |
| scipy | Sobel/Laplacian 纹理分析 | ~50MB |
| torch | CLIP 模型推理 | ~1.5GB |
| transformers | CLIP 模型加载 | ~300MB |
| open-clip-torch | CLIP 向量嵌入 | ~300MB |
| faiss-cpu | 向量相似度索引 | ~30MB |
| jinja2 | 画廊 HTML 模板 | ~1MB |
| tqdm | 进度条 | ~1MB |
| pydantic | 数据模型 | ~5MB |

首次 `uv sync` 总计约 2.5-3GB。

## 外部服务

### Cherry Studio API Server（可选）

用于 VLM 主观指标分析（`metrics --vlm`）和视觉标签（`analyze`）。

- 默认地址：`http://localhost:23333`
- 需要 API Key：通过 `--api-key` 参数传入
- 默认模型：`zhipu:glm-4.6v`（需支持图片输入）
- 可在 `config.py` 中修改默认模型

如果未启用 API Server，`metrics` 仍可仅计算像素指标（不加 `--vlm`）。

## 命令执行环境

所有命令必须在项目根目录下执行：

```bash
cd <project_root>/art-ref-collector && uv run python run.py <command> [args]
```

`uv run` 自动激活 `.venv` 并安装依赖，无需手动管理虚拟环境。

## 注意事项

1. **首次运行慢**：PyTorch + CLIP 模型首次下载约 2-3GB，后续运行正常
2. **scipy**：`pixel_metrics.py` 使用 `scipy.ndimage.sobel` 和 `scipy.ndimage.laplace`，必须安装
3. **网络**：搜索和下载需要网络连接；DuckDuckGo 可能有速率限制（403）
4. **图片损坏**：`pixel_metrics.py` 已处理 PIL 读取失败的情况，返回全零指标
5. **session 路径**：`store` 命令会移动图片到主题目录，之后 session 内路径失效，应使用主题目录路径
6. **画廊文件**：`canvas.html` 通过浏览器文件夹选择器加载本地图片，不依赖 HTTP 服务器提供图片
