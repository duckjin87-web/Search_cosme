"""조회 1건의 처리 흐름: 채널 수집 → 중복 제거 → 면 분류 → OCR → 판정 → 스냅샷 저장."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from app.adapters.base import AdapterError, ChannelAdapter
from app.models import FACES, FaceImage, Product, RawPage
from app.pipeline.judge import judge_all
from app.pipeline.vision import FaceClassifier, OcrEngine, image_hash
from app.store import Store

KST = timezone(timedelta(hours=9))
Emit = Callable[[dict], Awaitable[None] | None]


def now_kst() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


async def _emit(emit: Emit | None, event: dict) -> None:
    if emit is None:
        return
    r = emit(event)
    if asyncio.iscoroutine(r):
        await r


class Collector:
    def __init__(self, store: Store, ruleset: dict, classifier: FaceClassifier, ocr: OcrEngine):
        self.store = store
        self.ruleset = ruleset
        self.classifier = classifier
        self.ocr = ocr

    async def collect(self, product: Product, adapters: list[ChannelAdapter], emit: Emit | None = None,
                      lookup_id: str = "", collected_at: str | None = None) -> int:
        statuses = {a.channel: {"type": "channel", "channel": a.channel, "label": a.label, "tier": a.tier,
                                "status": "waiting", "message": "대기"} for a in adapters}
        for st in statuses.values():
            await _emit(emit, dict(st))
        pages: list[RawPage] = []

        async def run(a: ChannelAdapter) -> None:
            st = statuses[a.channel]
            st.update(status="collecting", message="수집 중")
            await _emit(emit, dict(st))
            started = now_kst()
            try:
                page = await a.fetch(product)
                if page is None:
                    st.update(status="done", message="이 채널에 상품 없음")
                else:
                    pages.append(page)
                    msg = f"이미지 {len(page.images)}장"
                    if page.detail_text:
                        msg += " + 상세 텍스트"
                    st.update(status="done", message=msg, source_url=page.source_url)
            except AdapterError as e:
                st.update(status="failed", message=str(e))
            except Exception as e:  # 어댑터 하나의 오류가 조회 전체를 멈추지 않게 한다
                st.update(status="failed", message=f"알 수 없는 오류: {e}")
            self.store.log_job(lookup_id, a.channel, st["status"], st["message"], started, now_kst())
            await _emit(emit, dict(st))

        # Tier 1을 먼저, 나머지는 동시에
        for a in sorted(adapters, key=lambda a: a.tier):
            if a.tier == 1:
                await run(a)
        await asyncio.gather(*(run(a) for a in adapters if a.tier != 1))

        await _emit(emit, {"type": "stage", "message": "면 분류 · OCR · 룰셋 판정"})
        pages.sort(key=lambda p: next(a.tier for a in adapters if a.channel == p.channel))
        sid = self.process(product, pages, list(statuses.values()), collected_at or now_kst())
        await _emit(emit, {"type": "done", "snapshot_id": sid})
        return sid

    def process(self, product: Product, pages: list[RawPage], channels: list[dict], collected_at: str) -> int:
        face_t = self.ruleset["thresholds"]["face_conf"]
        faces: dict[str, list[FaceImage]] = {f: [] for f in FACES}
        unclassified: list[FaceImage] = []
        details: list[tuple[str, str]] = []
        seen: set[str] = set()
        refs: dict[str, str] = {}
        dedup = 0

        for page in pages:
            if page.detail_text:
                details.append((page.channel, page.detail_text))
            for raw in page.images:
                h = image_hash(raw)
                if h in seen:
                    dedup += 1
                    continue
                seen.add(h)
                refs[h] = raw.image_id
                face, conf = self.classifier.classify(raw)
                img = FaceImage(h, page.channel, page.source_url, raw.width, raw.height, face, conf,
                                self.ocr.read(raw))
                if face in FACES and conf >= face_t:
                    faces[face].append(img)
                else:
                    unclassified.append(img)

        # 면별 대표 이미지: OCR 신뢰도, 해상도 순
        for imgs in faces.values():
            imgs.sort(key=lambda i: (i.ocr_conf, i.width * i.height), reverse=True)

        checks = judge_all(self.ruleset, product, faces, details)
        return self.store.save_snapshot(product, collected_at, self.ruleset["version"], channels, faces,
                                        unclassified, checks, dedup, refs)
