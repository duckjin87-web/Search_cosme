"""조회 1건: 채널 수집 → 중복 제거·저장 → 통이미지 분할 → OCR → 면 분류 → 룰셋 판정 → 스냅샷."""
from __future__ import annotations

import copy
import logging
import traceback
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select

from searchcosme.adapters.base import AdapterError, AdapterSkipped
from searchcosme.adapters.registry import all_adapters
from searchcosme.db import SessionLocal
from searchcosme.domain import FACES, FaceImage, ProductRef, RawPage
from searchcosme.models import Check, CheckValue, CollectJob, Face, Image, Lookup, LookupEvent, Product, Snapshot, now
from searchcosme.rules.judge import judge_all, load_ruleset
from searchcosme.storage import get_storage
from searchcosme.vision.classify import get_classifier
from searchcosme.vision.images import decode, slice_tall
from searchcosme.vision.ocr import get_ocr

log = logging.getLogger(__name__)


def emit(lookup_id: str, payload: dict) -> None:
    with SessionLocal() as db:
        db.add(LookupEvent(lookup_id=lookup_id, payload=payload))
        db.commit()


def product_ref(p: Product) -> ProductRef:
    return ProductRef(p.id, p.product_key, p.brand, p.name, p.volume, p.category, p.barcode)


def run_lookup(lookup_id: str, adapters: list | None = None) -> int | None:
    adapters = adapters or all_adapters()
    with SessionLocal() as db:
        lk = db.get(Lookup, lookup_id)
        ref = product_ref(db.get(Product, lk.product_id))
        lk.status = "running"
        db.commit()

    statuses: dict[str, dict] = {}
    try:
        for a in adapters:
            ok, why = a.enabled()
            statuses[a.channel] = {"type": "channel", "channel": a.channel, "label": a.label, "tier": a.tier,
                                   "status": "waiting" if ok else "skipped", "message": "대기" if ok else why}
            emit(lookup_id, dict(statuses[a.channel]))
        pages: list[RawPage] = []

        def run(a) -> None:
            st = statuses[a.channel]
            if st["status"] == "skipped":
                return
            st.update(status="collecting", message="수집 중")
            emit(lookup_id, dict(st))
            job_status, msg = "done", ""
            try:
                with SessionLocal() as db:
                    page = a.fetch(db, ref)
                if page is None:
                    msg = "연결된 자료 없음"
                else:
                    pages.append(page)
                    msg = f"이미지 {len(page.images)}장" + (" + 상세 텍스트" if page.detail_text else "")
                    if page.notes:
                        msg += f" · 일부 실패 {len(page.notes)}건"
                    st["source_url"] = page.source_url
            except AdapterSkipped as e:
                job_status, msg = "skipped", str(e)
            except AdapterError as e:
                job_status, msg = "failed", str(e)
            except Exception as e:  # 어댑터 하나의 오류가 조회 전체를 멈추지 않게 한다
                log.exception("adapter %s failed", a.channel)
                job_status, msg = "failed", f"알 수 없는 오류: {e}"
            st.update(status=job_status, message=msg)
            with SessionLocal() as db:
                db.add(CollectJob(lookup_id=lookup_id, channel=a.channel, status=job_status, message=msg, finished_at=now()))
                db.commit()
            emit(lookup_id, dict(st))

        for a in adapters:  # 사내 업로드·Tier 1 은 바로, 나머지는 동시에
            if a.tier <= 1:
                run(a)
        with ThreadPoolExecutor(max_workers=4) as ex:
            list(ex.map(run, [a for a in adapters if a.tier > 1]))

        emit(lookup_id, {"type": "stage", "message": "이미지 정리 · OCR · 면 분류 · 판정"})
        order = {a.channel: a.tier for a in adapters}
        pages.sort(key=lambda p: order.get(p.channel, 9))
        with SessionLocal() as db:
            sid = process(db, ref, pages, list(statuses.values()))
            lk = db.get(Lookup, lookup_id)
            lk.status, lk.snapshot_id, lk.finished_at = "done", sid, now()
            db.commit()
        emit(lookup_id, {"type": "done", "snapshot_id": sid})
        return sid
    except Exception as e:
        log.error("lookup %s failed: %s", lookup_id, traceback.format_exc())
        with SessionLocal() as db:
            lk = db.get(Lookup, lookup_id)
            lk.status, lk.error, lk.finished_at = "error", str(e), now()
            db.commit()
        emit(lookup_id, {"type": "error", "message": f"처리 중 오류: {e}"})
        return None


def _store_image(db, storage, dec, channel: str, source_url: str, parent: str | None) -> None:
    storage.put(dec.hash, dec.data, dec.mime)
    if db.get(Image, dec.hash) is None:
        db.add(Image(hash=dec.hash, storage_key=dec.hash, mime=dec.mime, width=dec.width, height=dec.height,
                     channel=channel, source_url=source_url, parent_hash=parent))
        db.flush()


def process(db, ref: ProductRef, pages: list[RawPage], channels: list[dict]) -> int:
    ruleset = copy.deepcopy(load_ruleset())
    ocr, clf = get_ocr(), get_classifier()
    th = ruleset["thresholds"]
    th["ocr_line_conf"] = th.get("ocr_line_conf_by_engine", {}).get(ocr.name, th["ocr_line_conf"])
    face_t = th["face_conf"]
    storage = get_storage()

    faces: dict[str, list[FaceImage]] = {f: [] for f in FACES}
    unclassified: list[FaceImage] = []
    details: list[tuple[str, str]] = []
    seen: set[str] = set()
    dedup = 0

    for page in pages:
        if page.detail_text:
            details.append((page.channel, page.detail_text))
        for raw in page.images:
            dec = decode(raw.data)
            if dec is None:
                continue
            if dec.hash in seen:
                dedup += 1
                continue
            seen.add(dec.hash)
            src = raw.image_url or page.source_url
            _store_image(db, storage, dec, page.channel, src, None)
            for seg in slice_tall(dec):
                parent = None if seg is dec else dec.hash
                if parent:
                    if seg.hash in seen:
                        continue
                    seen.add(seg.hash)
                    _store_image(db, storage, seg, page.channel, src, parent)
                lines = ocr.read(seg.image)
                face, conf, why = clf.classify(seg.image, lines, ref, raw.hint)
                if face == "side":
                    face = "left" if not faces["left"] else ("right" if not faces["right"] else "left")
                fi = FaceImage(seg.hash, page.channel, page.source_url, seg.width, seg.height, face, conf, why, lines, parent)
                if face in FACES and conf >= face_t:
                    faces[face].append(fi)
                else:
                    unclassified.append(fi)

    for imgs in faces.values():  # 대표 이미지: 지정 업로드 > OCR 신뢰도 > 해상도
        imgs.sort(key=lambda i: (i.face_conf >= 1.0, i.ocr_conf, i.width * i.height), reverse=True)
    checks = judge_all(ruleset, ref, faces, details)

    snap = Snapshot(product_id=ref.id, ruleset_version=ruleset["version"], channels=channels, dedup_count=dedup,
                    engine_info={"ocr": ocr.name, "classifier": clf.name, "ocr_line_conf": th["ocr_line_conf"]})
    db.add(snap)
    db.flush()
    for face, imgs in faces.items():
        for i, img in enumerate(imgs):
            db.add(_face_row(snap.id, face, img, i == 0))
    for img in unclassified:
        db.add(_face_row(snap.id, "unclassified", img, False))
    for c in checks:
        row = Check(snapshot_id=snap.id, item_id=c.item_id, item_name=c.item_name, basis=c.basis, faces=c.faces,
                    status=c.status.value, value=c.value, source=c.source, conflict=c.conflict, note=c.note)
        row.values = [CheckValue(source=o.source, channel=o.channel, face=o.face, value_raw=o.value) for o in c.observations]
        db.add(row)
    db.commit()
    return snap.id


def _face_row(sid: int, face: str, img: FaceImage, rep: bool) -> Face:
    return Face(snapshot_id=sid, face=face, image_hash=img.image_hash, channel=img.channel, source_url=img.source_url,
                face_conf=img.face_conf, face_reason=img.face_reason, ocr_conf=img.ocr_conf,
                ocr_lines=[{"text": l.text, "conf": l.conf} for l in img.lines], is_representative=rep)


def latest_events(db, lookup_id: str, after_id: int = 0) -> list[LookupEvent]:
    return db.scalars(select(LookupEvent).where(LookupEvent.lookup_id == lookup_id, LookupEvent.id > after_id)
                      .order_by(LookupEvent.id)).all()
