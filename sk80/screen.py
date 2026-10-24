"""Convert images and GIFs to the SK80's 160x96 RGB565 LCD format."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

from PIL import Image, ImageSequence

from . import constants as C

try:  # numpy makes GIF conversion much faster, but is optional
    import numpy as _np
except Exception:  # pragma: no cover
    _np = None

Frame = Tuple[Image.Image, int]  # (RGB image at 160x96, delay in ms)


def _resample(name: str):
    return {
        "nearest": Image.Resampling.NEAREST,
        "bilinear": Image.Resampling.BILINEAR,
        "bicubic": Image.Resampling.BICUBIC,
        "lanczos": Image.Resampling.LANCZOS,
    }.get(name, Image.Resampling.LANCZOS)


def prepare(
    image: Image.Image,
    fit: str = "cover",
    background: tuple[int, int, int] = (0, 0, 0),
    resample: str = "lanczos",
) -> Image.Image:
    """Return a 160x96 RGB image.

    ``fit`` is one of ``cover`` (fill and crop), ``contain`` (letterbox), or
    ``stretch``.
    """
    image = image.convert("RGB")
    target = (C.LCD_WIDTH, C.LCD_HEIGHT)

    if fit == "stretch":
        return image.resize(target, _resample(resample))

    if fit == "contain":
        scale = min(target[0] / image.width, target[1] / image.height)
        size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
        resized = image.resize(size, _resample(resample))
        canvas = Image.new("RGB", target, background)
        canvas.paste(resized, ((target[0] - size[0]) // 2, (target[1] - size[1]) // 2))
        return canvas

    # cover: scale to fill, then centre-crop.
    scale = max(target[0] / image.width, target[1] / image.height)
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    resized = image.resize(size, _resample(resample))
    left = (size[0] - target[0]) // 2
    top = (size[1] - target[1]) // 2
    return resized.crop((left, top, left + target[0], top + target[1]))


def to_rgb565(image: Image.Image) -> bytes:
    """Encode a 160x96 RGB image as little-endian RGB565 bytes."""
    image = image.convert("RGB")
    if image.size != (C.LCD_WIDTH, C.LCD_HEIGHT):
        image = image.resize((C.LCD_WIDTH, C.LCD_HEIGHT), Image.Resampling.LANCZOS)

    if _np is not None:
        arr = _np.asarray(image, dtype=_np.uint16)
        value = (
            ((arr[:, :, 0] >> 3) << 11)
            | ((arr[:, :, 1] >> 2) << 5)
            | (arr[:, :, 2] >> 3)
        )
        return value.astype("<u2", copy=False).tobytes()

    out = bytearray(C.LCD_WIDTH * C.LCD_HEIGHT * 2)
    offset = 0
    for r, g, b in image.getdata():
        value = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
        out[offset] = value & 0xFF
        out[offset + 1] = value >> 8
        offset += 2
    return bytes(out)


def load_frames(
    path: str | Path,
    fit: str = "cover",
    resample: str = "lanczos",
    max_frames: int = C.LCD_MAX_FRAMES,
    default_delay_ms: int = 1000,
) -> List[Frame]:
    """Load an image or animated GIF as ``(160x96 image, delay_ms)`` pairs."""
    path = Path(path)
    frames: List[Frame] = []
    with Image.open(path) as image:
        count = getattr(image, "n_frames", 1)
        for index, frame in enumerate(ImageSequence.Iterator(image)):
            if index >= max_frames:
                break
            delay = int(image.info.get("duration", 0) or 0)
            if delay <= 0:
                delay = default_delay_ms if count == 1 else 100
            frames.append((prepare(frame, fit=fit, resample=resample), delay))
    if not frames:
        raise ValueError(f"no frames found in {path}")
    return frames


def frames_from_image(
    image: Image.Image, fit: str = "cover", delay_ms: int = 100, resample: str = "lanczos"
) -> List[Frame]:
    return [(prepare(image, fit=fit, resample=resample), max(1, int(delay_ms)))]


def solid_frames(color: tuple[int, int, int], delay_ms: int = 100) -> List[Frame]:
    return [(Image.new("RGB", (C.LCD_WIDTH, C.LCD_HEIGHT), color), max(1, int(delay_ms)))]


def build_buffer(frames: Sequence[Frame]) -> bytes:
    """Build the exact buffer expected by :meth:`SK80.upload_screen`.

    Layout: 256-byte header, then one 30720-byte RGB565 frame per animation
    frame, padded with 0xFF to a 4096-byte boundary.
    """
    if not frames:
        raise ValueError("at least one frame is required")
    if len(frames) > C.LCD_MAX_FRAMES:
        frames = frames[: C.LCD_MAX_FRAMES]

    frame_size = C.LCD_WIDTH * C.LCD_HEIGHT * 2
    total = C.LCD_HEADER_SIZE + len(frames) * frame_size
    padded = ((total + C.PAGE_SIZE - 1) // C.PAGE_SIZE) * C.PAGE_SIZE
    data = bytearray([0xFF]) * padded

    data[0] = len(frames)
    for index, (_image, delay_ms) in enumerate(frames):
        # The firmware stores the frame delay in 2 ms units.
        data[1 + index] = max(1, min(255, round(max(1, delay_ms) / 2)))

    offset = C.LCD_HEADER_SIZE
    for image, _delay in frames:
        rgb = to_rgb565(image)
        data[offset : offset + frame_size] = rgb
        offset += frame_size

    return bytes(data)


def build_single(
    image: Image.Image,
    delay_ms: int = 1000,
    fit: str = "cover",
    resample: str = "lanczos",
) -> bytes:
    return build_buffer(frames_from_image(image, fit=fit, delay_ms=delay_ms, resample=resample))


def total_duration(frames: Sequence[Frame]) -> int:
    return sum(max(1, delay) for _image, delay in frames)
