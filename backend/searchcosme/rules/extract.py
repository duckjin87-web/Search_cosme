"""OCR·상세 텍스트에서 항목 값을 뽑는 함수들. 순수 함수만 둔다."""
from __future__ import annotations

import re
from dataclasses import dataclass

VOLUME_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(mL|ml|ML|g|G)\b(?:\s*\+\s*(\d+(?:\.\d+)?)\s*(mL|ml|ML|g|G)\b)?")


def kw_pattern(kw: str) -> re.Pattern:
    """키워드 글자 사이 공백을 허용한다 ('전 성 분' 도 '전성분'). OCR 띄어쓰기는 믿을 수 없다."""
    chars = [re.escape(c) for c in kw if not c.isspace()]
    return re.compile(r"\s*".join(chars))


def find_kw(text: str, kw: str) -> tuple[int, int] | None:
    m = kw_pattern(kw).search(text)
    return (m.start(), m.end()) if m else None


def normalize(text: str) -> str:
    """비교용 정규화: 공백·구두점·괄호 제거, 소문자."""
    return re.sub(r"[\s\.,·:;()\[\]{}<>/\-_'\"]+", "", text).lower()


@dataclass
class Extracted:
    value: str | None
    found_groups: list[str]
    missing_groups: list[str]


def _find_section(text: str, keywords: list[str], markers: list[str], single_line: bool = False) -> str | None:
    best = None
    for kw in keywords:
        hit = find_kw(text, kw)
        if hit and (best is None or hit[0] < best[0]):
            best = (hit[0], hit[1], kw)
    if best is None:
        return None
    rest = text[best[1]:]
    rest = re.sub(r"^[\s:：\)]+", "", rest)
    end = len(rest)
    for m in markers:
        if m in keywords:
            continue
        hit = find_kw(rest, m)
        if hit and hit[0] < end:
            end = hit[0]
    value = rest[:end]
    if single_line:
        value = value.split("\n", 1)[0]
    value = value.strip(" \n,;")
    value = re.sub(r"\s+", " ", value)
    if len(value) > 300:
        value = value[:300] + "…"
    return value or best[2]


def extract(item: dict, text: str, product_name: str, markers: list[str]) -> Extracted:
    kind = item["extract"]
    if not text:
        groups = [" / ".join(g) for g in item.get("groups", [])]
        return Extracted(None, [], groups)

    if kind == "product_name":
        ok = normalize(product_name) in normalize(text)
        return Extracted(product_name if ok else None, [], [])

    if kind == "volume":
        m = VOLUME_RE.search(text)
        return Extracted(m.group(0).replace(" ", "") if m else None, [], [])

    if kind == "keywords":
        hits = [k for k in item["keywords"] if find_kw(text, k)]
        return Extracted(", ".join(dict.fromkeys(hits)) if hits else None, [], [])

    if kind == "section":
        parts, found, missing = [], [], []
        for group in item["groups"]:
            v = _find_section(text, group, markers, bool(item.get("single_line")))
            label = group[0]
            if v is None:
                missing.append(label)
            else:
                found.append(label)
                parts.append(v if len(item["groups"]) == 1 else f"{label}: {v}")
        if missing:
            return Extracted(None, found, missing)
        return Extracted(" / ".join(parts), found, missing)

    raise ValueError(f"unknown extract kind: {kind}")
