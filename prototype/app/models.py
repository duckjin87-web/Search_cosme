"""도메인 모델. docs/plan.md 6절(데이터 모델)을 그대로 옮긴 것."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

FACES = ["front", "back", "left", "right", "top", "bottom"]

FACE_LABELS = {
    "container": {
        "front": "전면", "back": "후면", "left": "좌측면", "right": "우측면",
        "top": "상면(캡·펌프)", "bottom": "하면(바닥)",
    },
    "tube": {
        "front": "전면", "back": "후면", "left": "좌측면", "right": "우측면",
        "top": "상단(캡)", "bottom": "하단(씰링부)",
    },
}

CATEGORY_LABELS = {"container": "용기형", "tube": "튜브"}


class CheckStatus(str, Enum):
    OK = "ok"                      # 있음
    NONE = "none"                  # 없음: 면 확보 + 전부 판독 + 표기 없음
    UNREADABLE = "unreadable"      # 판독불가: 면은 있으나 판독 실패
    FACE_MISSING = "face_missing"  # 면 미확보


@dataclass
class OcrLine:
    text: str
    conf: float


@dataclass
class Product:
    product_key: str
    brand: str
    name: str
    volume: str
    category: str  # container | tube
    barcode: str | None = None


@dataclass
class Candidate:
    product: Product
    channel: str
    source_url: str
    title_raw: str


@dataclass
class RawImage:
    """채널에서 받은 이미지 한 장. fixture 필드는 프로토타입 전용(예시 데이터)."""
    image_id: str
    image_url: str
    width: int
    height: int
    fixture: dict = field(default_factory=dict)


@dataclass
class RawPage:
    channel: str
    source_url: str
    title_raw: str
    images: list[RawImage]
    detail_text: str | None = None


@dataclass
class FaceImage:
    image_hash: str
    channel: str
    source_url: str
    width: int
    height: int
    face: str
    face_conf: float
    lines: list[OcrLine]

    @property
    def ocr_conf(self) -> float:
        if not self.lines:
            return 0.0
        return round(sum(l.conf for l in self.lines) / len(self.lines), 3)


@dataclass
class Observation:
    source: str            # ocr | detail_text
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
