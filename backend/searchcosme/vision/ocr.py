"""OCR 엔진. 줄 단위 텍스트 + 신뢰도(0~1)를 돌려줘야 한다.
신뢰도가 없으면 '판독불가'와 '없음'을 구분할 수 없으므로 신뢰도를 주지 않는 엔진은 쓰지 않는다.
"""
from __future__ import annotations

import base64
import re
import time
import uuid
from typing import Protocol

from PIL import Image

from searchcosme.config import settings
from searchcosme.domain import OcrLine
from searchcosme.vision.images import to_jpeg

MEANINGFUL = re.compile(r"[0-9A-Za-z가-힣]")


def _keep(text: str) -> bool:
    return len(MEANINGFUL.findall(text)) >= 2


def merge_hangul_singles(text: str) -> str:
    """'정 제 수, 부 틸 렌' → '정제수, 부틸렌'. OCR 이 한글 음절을 한 자씩 띄어 읽은 구간만 붙인다."""
    single = re.compile(r"[가-힣][^\s가-힣]*")  # 한 음절 (+ 뒤에 붙은 구두점)
    out: list[str] = []
    run = False  # out[-1] 이 한 음절 토큰들로만 이루어졌는가
    for tok in text.split():
        is_single = bool(single.fullmatch(tok))
        if is_single and run and re.search(r"[가-힣]$", out[-1]):
            out[-1] += tok
        else:
            out.append(tok)
            run = is_single
    return " ".join(out)


class OcrEngine(Protocol):
    name: str

    def read(self, img: Image.Image) -> list[OcrLine]: ...


class TesseractOcr:
    """사내 서버에서 도는 오픈소스 엔진. 외부 전송이 없다."""
    name = "tesseract"

    def read(self, img: Image.Image) -> list[OcrLine]:
        import pytesseract

        g = img.convert("L")
        if g.width < 1400:  # 작은 글씨 판독을 위해 확대
            scale = min(3.0, 1400 / g.width)
            g = g.resize((int(g.width * scale), int(g.height * scale)), Image.LANCZOS)
        d = pytesseract.image_to_data(g, lang="kor+eng", config="--psm 4", output_type=pytesseract.Output.DICT)
        lines: dict[tuple, list[tuple[str, float]]] = {}
        for i, word in enumerate(d["text"]):
            conf = float(d["conf"][i])
            if not word.strip() or conf < 0:
                continue
            key = (d["block_num"][i], d["par_num"][i], d["line_num"][i])
            lines.setdefault(key, []).append((word, conf / 100))
        out = []
        for key in sorted(lines):
            words = lines[key]
            text = merge_hangul_singles(" ".join(w for w, _ in words))
            if _keep(text):
                out.append(OcrLine(text, round(sum(c for _, c in words) / len(words), 3)))
        return out


class ClovaOcr:
    """네이버 CLOVA OCR (General). 설정: CLOVA_OCR_URL, CLOVA_OCR_SECRET"""
    name = "clova"

    def __init__(self, client=None):
        import httpx
        self.client = client or httpx.Client(timeout=60)

    def read(self, img: Image.Image) -> list[OcrLine]:
        body = {"version": "V2", "requestId": uuid.uuid4().hex, "timestamp": int(time.time() * 1000),
                "images": [{"format": "jpg", "name": "img", "data": base64.b64encode(to_jpeg(img, 2400)).decode()}]}
        r = self.client.post(settings.clova_ocr_url, json=body, headers={"X-OCR-SECRET": settings.clova_ocr_secret or ""})
        r.raise_for_status()
        return parse_clova(r.json())


def parse_clova(data: dict) -> list[OcrLine]:
    out, words = [], []
    for f in (data.get("images") or [{}])[0].get("fields", []):
        words.append((f.get("inferText", ""), float(f.get("inferConfidence", 0))))
        if f.get("lineBreak"):
            text = " ".join(w for w, _ in words)
            if _keep(text):
                out.append(OcrLine(text, round(sum(c for _, c in words) / len(words), 3)))
            words = []
    if words:
        text = " ".join(w for w, _ in words)
        if _keep(text):
            out.append(OcrLine(text, round(sum(c for _, c in words) / len(words), 3)))
    return out


class GoogleVisionOcr:
    """Google Cloud Vision DOCUMENT_TEXT_DETECTION. 설정: GOOGLE_VISION_API_KEY"""
    name = "google"

    def __init__(self, client=None):
        import httpx
        self.client = client or httpx.Client(timeout=60)

    def read(self, img: Image.Image) -> list[OcrLine]:
        body = {"requests": [{"image": {"content": base64.b64encode(to_jpeg(img, 2400)).decode()},
                              "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
                              "imageContext": {"languageHints": ["ko", "en"]}}]}
        r = self.client.post("https://vision.googleapis.com/v1/images:annotate",
                             params={"key": settings.google_vision_key}, json=body)
        r.raise_for_status()
        return parse_google(r.json())


def parse_google(data: dict) -> list[OcrLine]:
    out = []
    ann = (data.get("responses") or [{}])[0].get("fullTextAnnotation") or {}
    for page in ann.get("pages", []):
        for block in page.get("blocks", []):
            for para in block.get("paragraphs", []):
                text, confs = "", []
                for word in para.get("words", []):
                    confs.append(float(word.get("confidence", 0)))
                    for sym in word.get("symbols", []):
                        text += sym.get("text", "")
                        brk = (sym.get("property") or {}).get("detectedBreak", {}).get("type")
                        if brk in ("SPACE", "SURE_SPACE"):
                            text += " "
                        elif brk in ("EOL_SURE_SPACE", "LINE_BREAK"):
                            if _keep(text):
                                out.append(OcrLine(text.strip(), round(sum(confs) / len(confs), 3)))
                            text, confs = "", []
                if text.strip() and confs and _keep(text):
                    out.append(OcrLine(text.strip(), round(sum(confs) / len(confs), 3)))
    return out


def get_ocr() -> OcrEngine:
    if settings.ocr_engine == "clova":
        return ClovaOcr()
    if settings.ocr_engine == "google":
        return GoogleVisionOcr()
    return TesseractOcr()
