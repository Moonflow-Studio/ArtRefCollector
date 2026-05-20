"""Compute pixel-level visual metrics from image data.

All metrics are normalized to 0-1 range.
Axis descriptions map low→high values to semantic scales.
"""
import numpy as np
from PIL import Image
from pathlib import Path


METRIC_AXES = {
    "brightness":       {"axis": "暗 ↔ 亮",           "unit": "avg luminance / 255"},
    "saturation":       {"axis": "灰 ↔ 鲜艳",         "unit": "avg HSV-S / 255"},
    "color_temperature":{"axis": "冷 ↔ 暖",           "unit": "warm pixel ratio"},
    "dominant_hue":     {"axis": "蓝绿(0) ↔ 红黄(1)", "unit": "circular mean hue"},
    "contrast":         {"axis": "柔和 ↔ 强对比",     "unit": "luminance std / 128"},
    "color_complexity": {"axis": "单纯 ↔ 丰富",       "unit": "hue histogram entropy"},
    "edge_density":     {"axis": "简洁 ↔ 复杂",       "unit": "edge pixel ratio"},
    "texture_complexity":{"axis": "平滑 ↔ 粗糙",      "unit": "Laplacian variance"},
    "composition_x":    {"axis": "左(0) ↔ 右(1)",     "unit": "gradient centroid x"},
    "composition_y":    {"axis": "上(0) ↔ 下(1)",     "unit": "gradient centroid y"},
    "spatial_openness":  {"axis": "封闭 ↔ 开阔",       "unit": "upper sky/empty ratio"},
}

# Human ratio placeholder — needs detection model
METRIC_AXES["human_ratio"] = {"axis": "环境(0) ↔ 角色(1)", "unit": "person area ratio (placeholder)"}


def _to_arrays(img_path: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Load image, return (rgb [H,W,3], hsv [H,W,3], gray [H,W]) uint8 arrays."""
    img = Image.open(img_path).convert("RGB")
    rgb = np.array(img, dtype=np.uint8)
    hsv = np.array(img.convert("HSV"), dtype=np.uint8)
    gray = np.array(img.convert("L"), dtype=np.uint8)
    return rgb, hsv, gray


def compute_brightness(gray: np.ndarray) -> float:
    return float(np.mean(gray) / 255.0)


def compute_saturation(hsv: np.ndarray) -> float:
    return float(np.mean(hsv[:, :, 1]) / 255.0)


def compute_color_temperature(hsv: np.ndarray) -> float:
    h = hsv[:, :, 0].astype(np.float32) * 2  # 0-360
    s = hsv[:, :, 1].astype(np.float32)
    warm = ((h < 60) | (h > 300)) & (s > 40)
    cool = (h > 160) & (h < 280) & (s > 40)
    total = max(np.sum(warm) + np.sum(cool), 1)
    return float(np.sum(warm) / total)


def compute_dominant_hue(hsv: np.ndarray) -> float:
    h = hsv[:, :, 0].astype(np.float32) * 2  # 0-360
    s = hsv[:, :, 1].astype(np.float32)
    mask = s > 30
    if mask.sum() < 10:
        return 0.5
    hues = h[mask]
    # Circular mean via sin/cos
    rad = np.deg2rad(hues)
    cx = float(np.mean(np.cos(rad)))
    cy = float(np.mean(np.sin(rad)))
    mean_deg = np.rad2deg(np.arctan2(cy, cx)) % 360
    # Map to 0-1: blue-green(180-270)→0, red-yellow(0-60)→1
    return float((mean_deg / 360.0))


def compute_contrast(gray: np.ndarray) -> float:
    return float(min(np.std(gray.astype(np.float32)) / 128.0, 1.0))


def compute_color_complexity(hsv: np.ndarray) -> float:
    h = hsv[:, :, 0].astype(np.int32)
    # 32-bin hue histogram
    bins = np.bincount(h.ravel() // 8, minlength=32)[:32]
    probs = bins / max(bins.sum(), 1)
    probs = probs[probs > 0]
    entropy = -float(np.sum(probs * np.log2(probs)))
    return float(min(entropy / 5.0, 1.0))  # 5 bits max → normalize


def compute_edge_density(gray: np.ndarray) -> float:
    from scipy.ndimage import sobel
    g = gray.astype(np.float32)
    sx = sobel(g, axis=1)
    sy = sobel(g, axis=0)
    mag = np.sqrt(sx ** 2 + sy ** 2)
    return float(np.mean(mag > 30))


def compute_texture_complexity(gray: np.ndarray) -> float:
    from scipy.ndimage import laplace
    g = gray.astype(np.float32)
    lap = laplace(g)
    var = float(np.var(lap))
    return float(min(var / 5000.0, 1.0))  # empirical normalization


def compute_composition(gray: np.ndarray) -> tuple[float, float]:
    from scipy.ndimage import sobel
    g = gray.astype(np.float32)
    sx = sobel(g, axis=1)
    sy = sobel(g, axis=0)
    mag = np.sqrt(sx ** 2 + sy ** 2)
    total = mag.sum()
    if total < 1:
        return 0.5, 0.5
    ys, xs = np.mgrid[0:mag.shape[0], 0:mag.shape[1]]
    cx = float((xs * mag).sum() / total / mag.shape[1])
    cy = float((ys * mag).sum() / total / mag.shape[0])
    return cx, cy


def compute_spatial_openness(gray: np.ndarray) -> float:
    h = gray.shape[0]
    upper = gray[:h // 3, :].astype(np.float32)
    # Low gradient in upper third → sky/open space
    from scipy.ndimage import sobel
    sx = sobel(upper, axis=1)
    sy = sobel(upper, axis=0)
    mag = np.sqrt(sx ** 2 + sy ** 2)
    low_grad_ratio = float(np.mean(mag < 15))
    return low_grad_ratio


def compute_all(image_path: str) -> dict:
    """Compute all pixel-level metrics for one image. Returns 0-1 normalized dict."""
    try:
        rgb, hsv, gray = _to_arrays(image_path)
    except Exception:
        return {k: 0.0 for k in METRIC_AXES}

    cx, cy = compute_composition(gray)

    return {
        "brightness":        round(compute_brightness(gray), 4),
        "saturation":        round(compute_saturation(hsv), 4),
        "color_temperature": round(compute_color_temperature(hsv), 4),
        "dominant_hue":      round(compute_dominant_hue(hsv), 4),
        "contrast":          round(compute_contrast(gray), 4),
        "color_complexity":  round(compute_color_complexity(hsv), 4),
        "edge_density":      round(compute_edge_density(gray), 4),
        "texture_complexity": round(compute_texture_complexity(gray), 4),
        "composition_x":     round(cx, 4),
        "composition_y":     round(cy, 4),
        "human_ratio":       0.0,
        "spatial_openness":  round(compute_spatial_openness(gray), 4),
    }
