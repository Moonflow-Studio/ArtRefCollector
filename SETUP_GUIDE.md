# Setup Guide

在新环境中手动配置 Art Reference Collector 的完整步骤。

## 1. 安装前置工具

### Python 3.12+

```bash
# macOS (Homebrew)
brew install python@3.12

# Ubuntu/Debian
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt install python3.12 python3.12-venv

# Windows
# 从 https://www.python.org/downloads/ 下载安装
# 或 winget install Python.Python.3.12
```

### uv 包管理器

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# 或 pip
pip install uv
```

验证安装：
```bash
uv --version
python3 --version   # 需要 >= 3.12
```

## 2. 获取项目代码

```bash
git clone https://github.com/Moonflow-Studio/ArtRefCollector.git
cd ArtRefCollector/art-ref-collector
```

## 3. 安装依赖

```bash
# uv 自动创建 .venv 并安装所有依赖
uv sync
```

这一步会下载约 2.5-3GB 的包（主要是 PyTorch 和 CLIP 模型运行时）。

如果网络较慢，可以先单独安装 PyTorch：

```bash
# 使用清华镜像加速（中国大陆）
uv pip install torch --index-url https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple
uv sync
```

验证安装：
```bash
uv run python -c "import torch; print('PyTorch', torch.__version__)"
uv run python -c "import scipy; print('scipy OK')"
uv run python -c "from PIL import Image; print('Pillow OK')"
```

## 4. 配置（可选）

### 修改默认 API 地址和模型

编辑 `config.py`：

```python
DEFAULT_API_BASE = "http://localhost:23333"    # API Server 地址
DEFAULT_MODEL = "zhipu:glm-4.6v"               # 默认视觉模型
```

### Cherry Studio API Server

如果需要 VLM 主观指标分析：

1. 打开 Cherry Studio → 设置 → API Server
2. 启用 API Server（默认端口 23333）
3. 确保至少有一个支持图片输入的模型可用
4. 使用时传入 API Key：
   ```bash
   uv run python run.py metrics --session <sid> --vlm --api-key <your_key>
   ```

## 5. 验证运行

```bash
# 测试搜索
uv run python run.py search "brutalist architecture" --max 5

# 查看帮助
uv run python run.py --help
uv run python run.py metrics --help
```

## 6. 画廊查看器

```bash
# 在项目根目录启动 HTTP 服务器
python -m http.server 8000
```

浏览器打开 `http://localhost:8000/gallery/canvas.html`。

注意：画廊通过浏览器文件夹选择器加载本地图片，不需要 HTTP 服务器提供图片文件。HTTP 服务器仅用于提供 `canvas.html` 本身。也可以直接双击 `canvas.html` 用浏览器打开。

## 7. 目录结构确认

安装完成后，项目目录应如下：

```
art-ref-collector/
├── .venv/                  # uv 创建的虚拟环境
├── analyze/                # 指标分析模块
│   ├── pixel_metrics.py    # 像素级指标
│   ├── vlm_metrics.py      # VLM 主观指标
│   └── vision_tagger.py    # 视觉标签
├── dedup/                  # 去重模块
│   ├── phash_dedup.py      # 感知哈希去重
│   └── clip_dedup.py       # CLIP 语义去重
├── display/                # 画廊生成
├── download/               # 下载模块
├── gallery/
│   └── canvas.html         # 无限画布查看器
├── search/                 # 搜索模块
├── store/                  # 存储和数据库
├── data/                   # 运行时数据（git 已忽略）
├── config.py               # 配置
├── run.py                  # CLI 入口
├── pyproject.toml          # 依赖声明
└── .python-version         # Python 版本锁定
```

## 故障排除

### uv sync 失败

```bash
# 清除缓存重试
uv cache clean
uv sync --reinstall
```

### PyTorch 安装问题

```bash
# 只安装 CPU 版本（更小）
uv pip install torch --index-url https://download.pytorch.org/whl/cpu
uv sync
```

### scipy 导入失败

```bash
uv pip install scipy
```

scipy 被 `pixel_metrics.py` 使用但可能不被 torch 自动拉取为依赖。

### DuckDuckGo 搜索 403

DuckDuckGo 有请求频率限制。等待几分钟后重试，或减少 `--max` 参数值。

### CLIP 模型下载缓慢

首次使用 `--clip` 去重时需下载约 600MB 模型。确保网络通畅，模型会缓存到 `~/.cache/huggingface/`。

### API Server 连接失败

1. 确认 Cherry Studio API Server 已启动
2. 检查端口是否正确（默认 23333）
3. 测试连接：`curl http://localhost:23333/v1/models`
