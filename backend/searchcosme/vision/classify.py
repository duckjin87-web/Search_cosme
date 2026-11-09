"""면 분류. 출력 = (면, 신뢰도 0~1, 근거).

- HeuristicClassifier (기본): OCR 텍스트와 이미지 비율로 판단. 외부 전송 없음.
- ClaudeVisionClassifier (선택): 이미지 자체를 보고 판단. ANTHROPIC_API_KEY 필요.
좌·우 측면은 사진만으로 구분하기 어려워 'side' 로 내고 파이프라인이 좌→우 순으로 배치한다.
"""
from __future__ import annotations

import base64
import json
import logging
import re
from typing import Protocol

from PIL import Image

from searchcosme.config import settings
from searchcosme.domain import OcrLine, ProductRef
from searchcosme.rules.extract import find_kw, normalize
from searchcosme.vision.images import to_jpeg

log = logging.getLogger(__name__)
FACE_CHOICES = ["front", "back", "side", "top", "bottom", "lifestyle", "other"]

BACK_KW = ("전성분", "제조업자", "책임판매업자", "제조판매업자", "사용방법", "사용법", "주의사항", "사용기한", "개봉 후", "고객상담")
SIDE_RE = re.compile(r"분리배출|재질|\b(PP|PE|PET|HDPE|LDPE|OTHER|PS)\b|88\d{11}")
BOTTOM_RE = re.compile(r"\bLOT\b|제조번호|\bEXP\b|\b20\d{2}[.\-/]\d{1,2}([.\-/]\d{1,2})?\b", re.I)


class FaceClassifier(Protocol):
    name: str

    def classify(self, img: Image.Image, lines: list[OcrLine], product: ProductRef,
                 hint: str | None) -> tuple[str, float, str]: ...


def _hinted(hint: str | None) -> tuple[str, float, str] | None:
    if hint and hint.startswith("face:"):
        face = hint.split(":", 1)[1]
        return face, 1.0, "업로드할 때 면을 지정함"
    return None


class HeuristicClassifier:
    name = "heuristic"

    def classify(self, img, lines, product, hint):
        hinted = _hinted(hint)
        if hinted:
            return hinted
        text = "\n".join(l.text for l in lines)
        norm = normalize(text)
        ratio = img.width / max(1, img.height)
        scores: dict[str, tuple[float, str]] = {}

        back_hits = [k for k in BACK_KW if find_kw(text, k)]
        if len(back_hits) >= 2:
            scores["back"] = (min(0.95, 0.55 + 0.1 * len(back_hits)), f"후면 표기어 {len(back_hits)}개: {', '.join(back_hits[:4])}")
        if SIDE_RE.search(text) and len(back_hits) < 2:
            scores["side"] = (0.75, f"분리배출·재질·바코드 표기: {SIDE_RE.search(text).group(0)}")
        if BOTTOM_RE.search(text) and len(lines) <= 4:
            scores["bottom"] = (0.8 if ratio > 1.6 else 0.7, f"제조번호·일자 각인: {BOTTOM_RE.search(text).group(0)}")
        name_hit = product.name and normalize(product.name) in norm
        brand_hit = product.brand and normalize(product.brand) in norm
        if (name_hit or brand_hit) and len(back_hits) < 2:
            s = 0.6 + (0.15 if name_hit else 0) + (0.1 if len(lines) <= 8 else 0)
            scores["front"] = (min(0.9, s), "제품명이 크게 보임" if name_hit else "브랜드명이 보임")
        if not scores:
            if not lines:
                return "lifestyle", 0.4, "글자가 없음 · 연출컷 또는 형상 사진일 수 있음"
            return "other", 0.3, "면을 판단할 표기를 찾지 못함"
        face, (conf, why) = max(scores.items(), key=lambda kv: kv[1][0])
        return face, round(conf, 2), why


SCHEMA = {
    "type": "object",
    "properties": {
        "face": {"type": "string", "enum": FACE_CHOICES},
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["face", "confidence", "reason"],
    "additionalProperties": False,
}

PROMPT = """화장품 패키지 사진 한 장이 어느 면을 찍은 것인지 분류하세요.
제품: {brand} {name} {volume} ({category})

- front: 제품명·브랜드가 크게 보이는 정면
- back: 전성분, 사용방법, 주의사항, 제조업자 등 작은 글씨 표시사항이 모인 면
- side: 좌·우 측면 (분리배출 마크, 바코드, 재질 표시 등)
- top: 위에서 본 캡·펌프
- bottom: 바닥 또는 튜브 끝 씰링부 (제조번호·사용기한 각인)
- lifestyle: 모델·소품이 있는 연출컷, 질감 사진, 홍보 이미지
- other: 위 어디에도 해당하지 않음

confidence 는 0~1 사이 숫자로, 확실하지 않으면 낮게 주세요. reason 은 한 문장 한국어로."""


class ClaudeVisionClassifier:
    name = "claude"

    def __init__(self, client=None, fallback: FaceClassifier | None = None):
        import anthropic
        self.anthropic = anthropic
        self.client = client or anthropic.Anthropic()
        self.fallback = fallback or HeuristicClassifier()

    def classify(self, img, lines, product, hint):
        hinted = _hinted(hint)
        if hinted:
            return hinted
        data = base64.standard_b64encode(to_jpeg(img, 1568)).decode()
        try:
            resp = self.client.beta.messages.create(
                model=settings.claude_model,
                max_tokens=2000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
                messages=[{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}},
                    {"type": "text", "text": PROMPT.format(brand=product.brand, name=product.name,
                                                           volume=product.volume, category=product.category)},
                ]}],
            )
        except self.anthropic.APIStatusError as e:
            log.warning("Claude 면 분류 실패 (%s), 규칙 기반으로 대체", e.status_code)
            return self.fallback.classify(img, lines, product, hint)
        except self.anthropic.APIConnectionError:
            log.warning("Claude 연결 실패, 규칙 기반으로 대체")
            return self.fallback.classify(img, lines, product, hint)
        if resp.stop_reason != "end_turn":
            return self.fallback.classify(img, lines, product, hint)
        text = next((b.text for b in resp.content if b.type == "text"), "")
        try:
            out = json.loads(text)
        except json.JSONDecodeError:
            return self.fallback.classify(img, lines, product, hint)
        conf = max(0.0, min(1.0, float(out.get("confidence", 0))))
        return out["face"], round(conf, 2), f"[Claude] {out.get('reason', '')}"


def get_classifier() -> FaceClassifier:
    if settings.face_classifier == "claude":
        return ClaudeVisionClassifier()
    return HeuristicClassifier()
