"""면 분류와 OCR 엔진 인터페이스.

프로토타입은 예시 데이터에 미리 적어둔 결과를 돌려주는 Fixture 구현만 있다.
실제 구현(비전 LLM 분류, CLOVA OCR / Google Vision / PaddleOCR)은
검증 게이트에서 비교한 뒤 같은 인터페이스로 붙인다.
"""
from __future__ import annotations

import hashlib
import json
from typing import Protocol

from app.models import OcrLine, RawImage


class FaceClassifier(Protocol):
    def classify(self, image: RawImage) -> tuple[str, float]:
        """(면, 신뢰도). 면 = front|back|left|right|top|bottom|lifestyle|other"""
        ...


class OcrEngine(Protocol):
    def read(self, image: RawImage) -> list[OcrLine]:
        """줄 단위 텍스트 + 신뢰도. 신뢰도가 없는 엔진은 쓰지 않는다(판독불가 판정 근거)."""
        ...


class FixtureFaceClassifier:
    def classify(self, image: RawImage) -> tuple[str, float]:
        return image.fixture.get("face", "other"), float(image.fixture.get("face_conf", 0.0))


class FixtureOcr:
    def read(self, image: RawImage) -> list[OcrLine]:
        return [OcrLine(l["text"], float(l["conf"])) for l in image.fixture.get("ocr", [])]


def image_hash(image: RawImage) -> str:
    """이미지 내용 해시. 실제로는 원본 바이트의 sha256.
    프로토타입은 예시 데이터의 내용 필드로 계산한다 → 같은 사진이면 채널이 달라도 같은 해시."""
    f = image.fixture
    content = f.get("content") or {"w": image.width, "h": image.height, "face": f.get("face"),
                                   "ocr": [l["text"] for l in f.get("ocr", [])]}
    return hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
