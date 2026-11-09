"""실제 Tesseract OCR · 면 분류 · 통이미지 분할."""
import io
import shutil

import pytest
from PIL import Image

from imagegen import BACK, BOTTOM, FRONT, SIDE, label
from searchcosme.domain import OcrLine, ProductRef
from searchcosme.vision.classify import HeuristicClassifier
from searchcosme.vision.images import decode, slice_tall
from searchcosme.vision.ocr import TesseractOcr, merge_hangul_singles, parse_clova, parse_google

needs_tesseract = pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract 미설치")
P = ProductRef(1, "k", "SAMPLECOS", "수분 장벽 크림", "50mL", "container")


def pil(data):
    return Image.open(io.BytesIO(data))


@needs_tesseract
def test_tesseract_reads_clear_back_label():
    lines = TesseractOcr().read(pil(label(BACK)))
    text = "\n".join(l.text for l in lines)
    assert "전성분" in text and "제조업자" in text
    assert min(l.conf for l in lines) >= 0.7


@needs_tesseract
def test_tesseract_blurred_label_is_low_confidence():
    lines = TesseractOcr().read(pil(label(BACK, size=14, width=520, blur=1.6, scale=0.6)))
    assert lines and min(l.conf for l in lines) < 0.7


def test_merge_hangul_singles():
    assert merge_hangul_singles("전 성 분: 정 제 수, 글리세린") == "전성분: 정제수, 글리세린"
    assert merge_hangul_singles("적 당 량 을 덜어 얼 굴 에") == "적당량을 덜어 얼굴에"


@pytest.mark.parametrize("lines,expected", [
    (BACK, "back"), (FRONT, "front"), (SIDE, "side"), (BOTTOM, "bottom"), ([], "lifestyle")])
def test_heuristic_classifier(lines, expected):
    img = Image.new("RGB", (900, 300) if expected == "bottom" else (800, 1000), "white")
    face, conf, why = HeuristicClassifier().classify(img, [OcrLine(t, 0.9) for t in lines], P, None)
    assert face == expected, why


def test_upload_hint_wins():
    img = Image.new("RGB", (800, 800), "white")
    assert HeuristicClassifier().classify(img, [], P, "face:right")[:2] == ("right", 1.0)


def test_slice_tall_detail_image():
    parts = [pil(label(BACK)), pil(label(FRONT, size=60, width=1100)), pil(label(SIDE, size=40, width=1100))]
    h = sum(p.height for p in parts) + 600
    tall = Image.new("RGB", (1100, max(h, 2600)), "white")
    y = 0
    for p in parts:
        tall.paste(p, (0, y))
        y += p.height + 200
    buf = io.BytesIO()
    tall.save(buf, "PNG")
    segs = slice_tall(decode(buf.getvalue()))
    assert len(segs) >= 2


def test_parse_clova():
    data = {"images": [{"fields": [
        {"inferText": "전성분:", "inferConfidence": 0.99, "lineBreak": False},
        {"inferText": "정제수", "inferConfidence": 0.95, "lineBreak": True},
        {"inferText": "LOT", "inferConfidence": 0.5, "lineBreak": True}]}]}
    lines = parse_clova(data)
    assert lines[0].text == "전성분: 정제수" and lines[0].conf == 0.97
    assert lines[1].conf == 0.5


def test_parse_google():
    def sym(t, brk=None):
        s = {"text": t}
        if brk:
            s["property"] = {"detectedBreak": {"type": brk}}
        return s
    data = {"responses": [{"fullTextAnnotation": {"pages": [{"blocks": [{"paragraphs": [{"words": [
        {"confidence": 0.9, "symbols": [sym("전"), sym("성"), sym("분", "SPACE")]},
        {"confidence": 0.8, "symbols": [sym("정"), sym("제"), sym("수", "LINE_BREAK")]},
    ]}]}]}]}}]}
    lines = parse_google(data)
    assert lines[0].text == "전성분 정제수" and lines[0].conf == 0.85
