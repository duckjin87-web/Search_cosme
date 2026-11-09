"""이미지 디코딩·해시·상세페이지 통이미지 분할."""
from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass

from PIL import Image, ImageOps

TALL_RATIO = 2.2      # 높이/너비가 이 값을 넘으면 상세페이지 통이미지로 보고 자른다
MIN_SIDE = 80         # 너무 작은 이미지는 버린다 (아이콘 등)


@dataclass
class Decoded:
    data: bytes
    mime: str
    width: int
    height: int
    hash: str
    image: Image.Image


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def decode(data: bytes) -> Decoded | None:
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:
        return None
    img = ImageOps.exif_transpose(img)
    if img.width < MIN_SIDE or img.height < MIN_SIDE:
        return None
    mime = Image.MIME.get(img.format or "", "image/jpeg")
    return Decoded(data, mime, img.width, img.height, sha256(data), img.convert("RGB"))


def to_jpeg(img: Image.Image, max_side: int | None = None, quality: int = 90) -> bytes:
    if max_side and max(img.size) > max_side:
        img = img.copy()
        img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def _blank_rows(img: Image.Image) -> list[bool]:
    """행마다 '거의 단색'인지. 축소한 흑백 이미지로 빠르게 본다."""
    small = img.convert("L")
    small = small.resize((min(160, small.width), small.height))
    w = small.width
    px = small.tobytes()
    out = []
    for y in range(small.height):
        row = px[y * w:(y + 1) * w]
        out.append(max(row) - min(row) < 18)
    return out


def slice_tall(dec: Decoded) -> list[Decoded]:
    """세로로 긴 상세페이지 이미지를 여백 줄에서 잘라 컷 단위로 나눈다."""
    img = dec.image
    if img.height <= img.width * TALL_RATIO:
        return [dec]
    blank = _blank_rows(img)
    target_min, target_max = int(img.width * 0.6), int(img.width * 2.0)
    cuts, start, y = [], 0, 0
    while y < img.height:
        if y - start >= target_min and blank[y]:
            run_end = y
            while run_end < img.height and blank[run_end]:
                run_end += 1
            cut = (y + run_end) // 2
            cuts.append((start, cut))
            start, y = cut, run_end
            continue
        if y - start >= target_max:
            cuts.append((start, y))
            start = y
        y += 1
    if img.height - start > MIN_SIDE:
        cuts.append((start, img.height))
    out = []
    for top, bottom in cuts:
        seg = img.crop((0, top, img.width, bottom))
        if all(blank[top:bottom]):
            continue
        data = to_jpeg(seg)
        d = decode(data)
        if d:
            out.append(d)
    return out or [dec]
