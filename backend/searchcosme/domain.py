"""파이프라인 안에서 주고받는 값. DB 모델(models.py)과 분리한다."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

FACES = ["front", "back", "left", "right", "top", "bottom"]
FACE_LABELS = {
    "container": {"front": "전면", "back": "후면", "left": "좌측면", "right": "우측면",
                  "top": "상면(캡·펌프)", "bottom": "하면(바닥)"},
    "tube": {"front": "전면", "back": "후면", "left": "좌측면", "right": "우측면",
             "top": "상단(캡)", "bottom": "하단(씰링부)"},
}
CATEGORY_LABELS = {"container": "용기형", "tube": "튜브"}
CHANNEL_LABELS = {"naver": "네이버쇼핑", "hwahae": "화해", "brand": "브랜드 자사몰", "upload": "사내 업로드"}


class CheckStatus(str, Enum):
    OK = "ok"
    NONE = "none"
    UNREADABLE = "unreadable"
    FACE_MISSING = "face_missing"


@dataclass
class OcrLine:
    text: str
    conf: float  # 0~1


@dataclass
class ProductRef:
    id: int
    product_key: str
    brand: str
    name: str
    volume: str
    category: str
    barcode: str | None = None


@dataclass
class Candidate:
    channel: str
    brand: str
    name: str
    volume: str
    category_guess: str
    title_raw: str
    source_url: str
    image_url: str | None = None
    external_id: str | None = None
    barcode: str | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class RawImage:
    data: bytes
    source_url: str          # 이미지가 있던 페이지 또는 이미지 URL
    image_url: str | None = None
    hint: str | None = None  # 'upload' 등 출처 힌트


@dataclass
class RawPage:
    channel: str
    source_url: str
    title_raw: str
    images: list[RawImage]
    detail_text: str | None = None
    notes: list[str] = field(default_factory=list)


@dataclass
class FaceImage:
    image_hash: str
    channel: str
    source_url: str
    width: int
    height: int
    face: str
    face_conf: float
    face_reason: str
    lines: list[OcrLine]
    parent_hash: str | None = None

    @property
    def ocr_conf(self) -> float:
        if not self.lines:
            return 0.0
        return round(sum(l.conf for l in self.lines) / len(self.lines), 3)


@dataclass
class Observation:
    source: str
    channel: str
    value: str
    face: str | None = None


@dataclass
class CheckResult:
    item_id: str
    item_name: str
    basis: str
    faces: list[str]
    status: CheckStatus
    value: str | None
    source: str | None
    conflict: bool
    note: str
    observations: list[Observation] = field(default_factory=list)
