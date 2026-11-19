"""Accent / dim ASS colours sampled from a still background image."""

from __future__ import annotations

from pathlib import Path
from typing import Any

_GOLD = "&H0037AFD4"
_DIM = "&H00CCCCCC"


def rgb_to_ass(r: int, g: int, b: int) -> str:
    """ASS primary colour is &HAABBGGRR (alpha first, then BGR)."""
    return f"&H00{int(b) & 0xFF:02X}{int(g) & 0xFF:02X}{int(r) & 0xFF:02X}"


def _clamp_byte(value: float) -> int:
    return max(0, min(255, int(round(value))))


def sample_image_palette(image: Path) -> tuple[str, str, dict[str, Any]]:
    """Pick a sung accent + waiting dim colour from one still.

    Weights mid/high-chroma pixels so near-black / grey do not win, then lifts
    saturation for the hit colour and softens it for the waiting state. Falls
    back to a locked gold/dim pair when sampling fails.
    """
    meta: dict[str, Any] = {"sung": _GOLD, "dim": _DIM, "source": "fallback"}
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        return _GOLD, _DIM, meta

    try:
        arr = np.asarray(Image.open(image).convert("RGB"), dtype=np.float32)
    except Exception:  # noqa: BLE001
        return _GOLD, _DIM, meta
    if arr.size < 100:
        return _GOLD, _DIM, meta

    # Downsample so a 4K plate does not dominate the mean.
    h, w = arr.shape[:2]
    step = max(1, int(round(min(h, w) / 160.0)))
    rgb = arr[::step, ::step].reshape(-1, 3)
    r, g, b = rgb[:, 0], rgb[:, 1], rgb[:, 2]
    luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
    maxc = rgb.max(axis=1)
    minc = rgb.min(axis=1)
    chroma = maxc - minc
    sat = np.where(maxc > 1.0, chroma / np.maximum(maxc, 1.0), 0.0)
    weight = (sat ** 1.1) * np.clip((luma - 18.0) / 180.0, 0.05, 1.0)
    w_sum = float(weight.sum())
    if w_sum < 1.0:
        return _GOLD, _DIM, meta

    mean = (rgb * weight[:, None]).sum(axis=0) / w_sum
    mr, mg, mb = float(mean[0]), float(mean[1]), float(mean[2])
    max_chan = max(mr, mg, mb, 1.0)
    boost = 255.0 / max_chan
    accent_r = _clamp_byte(mr * boost * 0.92 + 20)
    accent_g = _clamp_byte(mg * boost * 0.92 + 20)
    accent_b = _clamp_byte(mb * boost * 0.92 + 20)
    accent_chroma = max(accent_r, accent_g, accent_b) - min(accent_r, accent_g, accent_b)
    if accent_chroma < 40:
        accent_r, accent_g, accent_b = 0xD4, 0xAF, 0x37
    dim_r = _clamp_byte(accent_r * 0.55 + 90)
    dim_g = _clamp_byte(accent_g * 0.55 + 90)
    dim_b = _clamp_byte(accent_b * 0.55 + 90)
    sung = rgb_to_ass(accent_r, accent_g, accent_b)
    dim = rgb_to_ass(dim_r, dim_g, dim_b)
    meta = {
        "sung": sung,
        "dim": dim,
        "source": "image",
        "rgb_sung": [accent_r, accent_g, accent_b],
        "rgb_dim": [dim_r, dim_g, dim_b],
        "frames": 1,
        "rgb_mean": [round(mr), round(mg), round(mb)],
        "path": str(image),
    }
    return sung, dim, meta


DEFAULT_SUNG = _GOLD
DEFAULT_DIM = _DIM
