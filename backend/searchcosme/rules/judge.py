"""룰셋 판정. docs/ruleset.md 의 4상태 규칙을 코드로 옮긴 것.

판정 순서 (먼저 맞는 조건에서 멈춘다)
1. 어느 소스에서든 값을 찾음            → ok
2. 항목의 확인 면이 하나도 확보되지 않음 → face_missing
3. 확보된 면에 기준 미만 신뢰도 줄이 있음 → unreadable
4. 확보된 면을 전부 읽었는데 없음        → none

none 은 "다 읽었다"는 증거가 있을 때만 나온다. 애매하면 unreadable 이다.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from searchcosme.domain import CHANNEL_LABELS, FACE_LABELS, CheckResult, CheckStatus, FaceImage, Observation, ProductRef
from searchcosme.rules.extract import extract, normalize

RULESET_PATH = Path(__file__).resolve().parent / "ruleset.yaml"



def load_ruleset(path: Path = RULESET_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _ch(channel: str) -> str:
    return CHANNEL_LABELS.get(channel, channel)


def judge_item(
    item: dict,
    ruleset: dict,
    product: ProductRef,
    faces: dict[str, list[FaceImage]],
    details: list[tuple[str, str]],
) -> CheckResult:
    threshold = ruleset["thresholds"]["ocr_line_conf"]
    markers = ruleset["section_markers"]
    labels = FACE_LABELS[product.category]
    item_faces: list[str] = item["faces"]

    observations: list[Observation] = []
    partial_found: set[str] = set()
    captured: list[str] = []
    low_conf: list[tuple[str, float]] = []

    for face in item_faces:
        images = faces.get(face, [])
        if not images:
            continue
        captured.append(face)
        for img in images:
            if not img.lines:
                low_conf.append((face, 0.0))
            readable = [l for l in img.lines if l.conf >= threshold]
            if len(readable) < len(img.lines):
                low_conf.append((face, min(l.conf for l in img.lines)))
            text = "\n".join(l.text for l in readable)
            r = extract(item, text, product.name, markers)
            if r.value:
                observations.append(Observation("ocr", img.channel, r.value, face))
            partial_found.update(r.found_groups)

    detail_partial: set[str] = set()
    if item.get("detail_text"):
        for channel, text in details:
            r = extract(item, text, product.name, markers)
            if r.value:
                observations.append(Observation("detail_text", channel, r.value))
            detail_partial.update(r.found_groups)

    base = dict(item_id=item["id"], item_name=item["name"], basis=item["basis"], faces=item_faces)

    # 1. 값을 찾음
    if observations:
        # 값 비교는 원문을 뽑는 항목(구간·용량)만 한다. 키워드·제품명은 '있다'만 확인.
        # 다른 면끼리는 보완 관계일 수 있다 (후면 "별도 표기" + 하면 "EXP 2028.09").
        # 같은 면의 값끼리, 또는 면 OCR 과 상세 텍스트가 다를 때만 충돌로 본다.
        comparable = item["extract"] in ("section", "volume")
        conflict = comparable and any(
            normalize(a.value) != normalize(b.value)
            for i, a in enumerate(observations) for b in observations[i + 1:]
            if a.face == b.face or a.face is None or b.face is None)
        ocr_obs = [o for o in observations if o.source == "ocr"]
        primary = ocr_obs[0] if ocr_obs else observations[0]
        notes = []
        where = sorted({f"{labels[o.face]} OCR · {_ch(o.channel)}" if o.face else f"{_ch(o.channel)} 상세 텍스트" for o in observations})
        notes.append("근거: " + ", ".join(where))
        if not ocr_obs:
            notes.append("패키지 면에서는 확인 못 함 · 상세 텍스트 기준")
        if conflict:
            notes.append("채널 간 표기가 서로 다름 · 확인 필요")
        return CheckResult(**base, status=CheckStatus.OK, value=primary.value, source=primary.source,
                           conflict=conflict, note=" / ".join(notes), observations=observations)

    found_any = sorted(partial_found | detail_partial)
    partial_note = ""
    if found_any:
        missing = [g[0] for g in item.get("groups", []) if g[0] not in found_any]
        partial_note = f" / {', '.join(found_any)} 확인, {', '.join(missing)} 미확인"

    # 2. 면 미확보
    if not captured:
        need = ", ".join(labels[f] for f in item_faces)
        return CheckResult(**base, status=CheckStatus.FACE_MISSING, value=None, source=None, conflict=False,
                           note=f"필요 면 미확보: {need}" + partial_note)

    # 3. 판독불가
    if low_conf:
        worst = min(c for _, c in low_conf)
        faces_txt = ", ".join(sorted({labels[f] for f, _ in low_conf}))
        why = "OCR 결과 없음" if worst == 0.0 else f"최저 신뢰도 {worst:.2f} < 기준 {threshold:.2f}"
        return CheckResult(**base, status=CheckStatus.UNREADABLE, value=None, source=None, conflict=False,
                           note=f"{faces_txt} 판독 실패 ({why})" + partial_note)

    # 4. 없음
    note = f"{', '.join(labels[f] for f in captured)} 전체 판독됨 · 표기 확인 안 됨" + partial_note
    if item.get("conditional"):
        note += f" / {item['conditional']}"
    return CheckResult(**base, status=CheckStatus.NONE, value=None, source=None, conflict=False, note=note)


def judge_all(ruleset: dict, product: ProductRef, faces: dict[str, list[FaceImage]],
              details: list[tuple[str, str]]) -> list[CheckResult]:
    return [judge_item(item, ruleset, product, faces, details) for item in ruleset["items"]]


__all__ = ["load_ruleset", "judge_all", "judge_item"]
