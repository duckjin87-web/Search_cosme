"""테스트용 패키지 면 이미지 생성 (나눔고딕). 실제 사진 대신 쓰는 합성 이미지."""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT_CANDIDATES = ["/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
                   "/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf"]


def font(size: int) -> ImageFont.FreeTypeFont:
    for p in FONT_CANDIDATES:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    raise RuntimeError("Korean font not found (apt install fonts-nanum)")


def label(lines: list[str], size: int = 28, width: int = 1100, blur: float = 0, scale: float = 1.0) -> bytes:
    f = font(size)
    h = 80 + len(lines) * int(size * 1.6)
    img = Image.new("RGB", (width, h), "white")
    d = ImageDraw.Draw(img)
    y = 40
    for line in lines:
        d.text((40, y), line, fill="black", font=f)
        y += int(size * 1.6)
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(blur))
    if scale != 1.0:
        img = img.resize((int(img.width * scale), int(img.height * scale)))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


BACK = [
    "수분 장벽 크림",
    "용량: 50mL",
    "전성분: 정제수, 글리세린, 부틸렌글라이콜, 판테놀, 카보머",
    "사용방법: 적당량을 덜어 얼굴에 펴 바릅니다.",
    "주의사항: 상처가 있는 부위에는 사용을 자제할 것",
    "사용기한: 별도 표기일까지",
    "제조업자: 샘플코스메틱 주식회사",
    "책임판매업자: 주식회사 샘플코스",
]
FRONT = ["SAMPLECOS", "수분 장벽 크림", "50mL"]
SIDE = ["분리배출 용기 PP 캡 PP", "8800000000017"]
BOTTOM = ["LOT 2509A12", "EXP 2028.09"]
