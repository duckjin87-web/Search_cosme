"""화장품 표시사항 사전검토 — API 서버.

실행:  uvicorn searchcosme.api:app   (backend/ 디렉터리에서)
"""
from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from searchcosme.adapters.base import AdapterError, AdapterSkipped
from searchcosme.adapters.registry import adapter, all_adapters
from searchcosme.config import settings
from searchcosme.db import SessionLocal, init_db
from searchcosme.domain import CATEGORY_LABELS, FACE_LABELS
from searchcosme.models import CollectJob, Image, Listing, Lookup, LookupEvent, Product, Snapshot, Upload, now
from searchcosme.rules.extract import normalize
from searchcosme.rules.judge import load_ruleset
from searchcosme.storage import get_storage
from searchcosme.tasks import dispatch
from searchcosme.views import STATUS_LABELS, compare_view, product_view, snapshot_list, snapshot_view
from searchcosme.vision.images import decode

HERE = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="화장품 표시사항 사전검토", lifespan=lifespan)


def get_db():
    with SessionLocal() as db:
        yield db


def make_key(brand: str, name: str, volume: str, barcode: str | None) -> str:
    return f"bc:{barcode}" if barcode else normalize(f"{brand}|{name}|{volume}") or uuid.uuid4().hex


# ---------------------------------------------------------------- 메타
@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.get("/api/meta")
def meta() -> dict:
    rs = load_ruleset()
    return {
        "today": now().isoformat()[:10], "ruleset_version": rs["version"], "items": rs["items"],
        "face_labels": FACE_LABELS, "category_labels": CATEGORY_LABELS, "status_labels": STATUS_LABELS,
        "channels": [{"channel": a.channel, "label": a.label, "tier": a.tier, "searchable": a.searchable,
                      "enabled": a.enabled()[0], "reason": a.enabled()[1]} for a in all_adapters()],
        "engines": {"ocr": settings.ocr_engine, "classifier": settings.face_classifier, "queue": settings.queue},
    }


# ---------------------------------------------------------------- 후보·제품
class CandidateQuery(BaseModel):
    query: str
    category: str | None = None


@app.post("/api/candidates")
def candidates(q: CandidateQuery, db: Session = Depends(get_db)) -> dict:
    text = q.query.strip()
    if not text:
        raise HTTPException(400, "제품명을 입력하세요.")
    like = f"%{text}%"
    rows = db.scalars(select(Product).where(or_(Product.name.ilike(like), Product.brand.ilike(like),
                                                Product.barcode == text)).limit(20)).all()
    if q.category:
        rows = [p for p in rows if p.category == q.category]
    known = [product_view(db, p) for p in rows]
    external, notices = [], []
    for a in all_adapters():
        if not a.searchable:
            continue
        try:
            for c in a.search(text):
                external.append({"channel": c.channel, "channel_label": a.label, "brand": c.brand, "name": c.name,
                                 "volume": c.volume, "category": q.category or c.category_guess, "title_raw": c.title_raw,
                                 "source_url": c.source_url, "image_url": c.image_url, "external_id": c.external_id,
                                 "extra": c.extra})
        except AdapterSkipped as e:
            notices.append(f"{a.label}: {e}")
        except AdapterError as e:
            notices.append(f"{a.label}: {e}")
    return {"known": known, "external": external, "notices": notices}


class ProductIn(BaseModel):
    brand: str = ""
    name: str
    volume: str = ""
    category: str = "container"
    barcode: str | None = None
    listing: dict | None = None  # 후보에서 만들 때: {channel, source_url, title_raw, image_url, external_id}


@app.post("/api/products")
def create_product(body: ProductIn, db: Session = Depends(get_db)) -> dict:
    if body.category not in CATEGORY_LABELS:
        raise HTTPException(400, "카테고리는 container 또는 tube 입니다.")
    if not body.name.strip():
        raise HTTPException(400, "제품명을 입력하세요.")
    key = make_key(body.brand, body.name, body.volume, body.barcode or None)
    p = db.scalar(select(Product).where(Product.product_key == key))
    if p is None:
        p = Product(product_key=key, brand=body.brand.strip(), name=body.name.strip(), volume=body.volume.strip(),
                    category=body.category, barcode=body.barcode or None)
        db.add(p)
        db.flush()
    if body.listing and body.listing.get("source_url"):
        l = body.listing
        exists = db.scalar(select(Listing).where(Listing.product_id == p.id, Listing.channel == l["channel"],
                                                 Listing.source_url == l["source_url"]))
        if not exists:
            db.add(Listing(product_id=p.id, channel=l["channel"], source_url=l["source_url"],
                           title_raw=l.get("title_raw", ""), image_url=l.get("image_url"),
                           external_id=l.get("external_id"), raw=l.get("extra") or {}))
    db.commit()
    return product_view(db, p)


def _product(db: Session, pid: int) -> Product:
    p = db.get(Product, pid)
    if p is None:
        raise HTTPException(404, "제품을 찾을 수 없습니다.")
    return p


@app.get("/api/products/{pid}")
def get_product(pid: int, db: Session = Depends(get_db)) -> dict:
    return product_view(db, _product(db, pid))


class ListingIn(BaseModel):
    channel: str
    url: str


@app.post("/api/products/{pid}/listings")
def add_listing(pid: int, body: ListingIn, db: Session = Depends(get_db)) -> dict:
    p = _product(db, pid)
    if body.channel not in ("hwahae", "brand"):
        raise HTTPException(400, "URL 로 연결할 수 있는 채널은 화해, 브랜드 자사몰입니다.")
    if not body.url.startswith(("http://", "https://")):
        raise HTTPException(400, "http:// 또는 https:// 로 시작하는 주소를 넣으세요.")
    try:
        adapter(body.channel).check_url(body.url)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not db.scalar(select(Listing).where(Listing.product_id == pid, Listing.channel == body.channel,
                                           Listing.source_url == body.url)):
        db.add(Listing(product_id=pid, channel=body.channel, source_url=body.url, title_raw=""))
        db.commit()
    return product_view(db, p)


@app.delete("/api/listings/{lid}")
def delete_listing(lid: int, db: Session = Depends(get_db)) -> dict:
    l = db.get(Listing, lid)
    if l is None:
        raise HTTPException(404, "연결을 찾을 수 없습니다.")
    pid = l.product_id
    db.delete(l)
    db.commit()
    return product_view(db, _product(db, pid))


@app.post("/api/products/{pid}/uploads")
async def upload_images(pid: int, files: list[UploadFile] = File(...), face_hint: str = Form(""),
                        detail_text: str = Form(""), db: Session = Depends(get_db)) -> dict:
    p = _product(db, pid)
    if face_hint and face_hint not in FACE_LABELS["container"]:
        raise HTTPException(400, "면 지정 값이 올바르지 않습니다.")
    storage, added, rejected = get_storage(), 0, []
    for f in files:
        data = await f.read()
        if len(data) > settings.upload_max_mb * 1024 * 1024:
            rejected.append(f"{f.filename}: {settings.upload_max_mb}MB 초과")
            continue
        dec = decode(data)
        if dec is None:
            rejected.append(f"{f.filename}: 이미지가 아니거나 너무 작음")
            continue
        storage.put(dec.hash, dec.data, dec.mime)
        if db.get(Image, dec.hash) is None:
            db.add(Image(hash=dec.hash, storage_key=dec.hash, mime=dec.mime, width=dec.width, height=dec.height,
                         channel="upload", source_url=f"upload:{f.filename}"))
            db.flush()
        db.add(Upload(product_id=pid, image_hash=dec.hash, face_hint=face_hint or None, detail_text=detail_text or None))
        added += 1
    if detail_text and not files:
        raise HTTPException(400, "사진을 한 장 이상 올리세요.")
    db.commit()
    return {"added": added, "rejected": rejected, "product": product_view(db, p)}


@app.delete("/api/uploads/{uid}")
def delete_upload(uid: int, db: Session = Depends(get_db)) -> dict:
    u = db.get(Upload, uid)
    if u is None:
        raise HTTPException(404, "업로드를 찾을 수 없습니다.")
    pid = u.product_id
    db.delete(u)
    db.commit()
    return product_view(db, _product(db, pid))


# ---------------------------------------------------------------- 조회(수집·판정)
class LookupIn(BaseModel):
    refresh: bool = False


@app.post("/api/products/{pid}/lookups")
def start_lookup(pid: int, body: LookupIn, db: Session = Depends(get_db)) -> dict:
    _product(db, pid)
    today = now().isoformat()[:10]
    latest = db.scalar(select(Snapshot).where(Snapshot.product_id == pid).order_by(Snapshot.collected_at.desc()))
    if latest and latest.collected_at.isoformat()[:10] == today and not body.refresh:
        return {"status": "cached", "snapshot_id": latest.id}
    running = db.scalar(select(Lookup).where(Lookup.product_id == pid, Lookup.status.in_(["queued", "running"])))
    if running:
        return {"status": "collecting", "lookup_id": running.id}
    lk = Lookup(id=uuid.uuid4().hex[:16], product_id=pid)
    db.add(lk)
    db.commit()
    dispatch(lk.id)
    return {"status": "collecting", "lookup_id": lk.id}


@app.get("/api/lookups/{lookup_id}/events")
async def lookup_events(lookup_id: str) -> StreamingResponse:
    with SessionLocal() as db:
        if db.get(Lookup, lookup_id) is None:
            raise HTTPException(404, "조회를 찾을 수 없습니다.")

    async def stream():
        last, idle = 0, 0
        while True:
            with SessionLocal() as db:
                evs = db.scalars(select(LookupEvent).where(LookupEvent.lookup_id == lookup_id, LookupEvent.id > last)
                                 .order_by(LookupEvent.id)).all()
                status = db.get(Lookup, lookup_id).status
            for ev in evs:
                last = ev.id
                yield f"data: {json.dumps(ev.payload, ensure_ascii=False)}\n\n"
            if status in ("done", "error") and not evs:
                break
            idle = 0 if evs else idle + 1
            if idle and idle % 30 == 0:
                yield ": keepalive\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(stream(), media_type="text/event-stream")


# ---------------------------------------------------------------- 결과
@app.get("/api/products/{pid}/snapshots")
def snapshots(pid: int, date_from: str | None = None, date_to: str | None = None, db: Session = Depends(get_db)) -> list[dict]:
    _product(db, pid)
    return snapshot_list(db, pid, date_from, date_to)


@app.get("/api/snapshots/compare")
def compare(a: int, b: int, db: Session = Depends(get_db)) -> dict:
    va, vb = snapshot_view(db, a), snapshot_view(db, b)
    if not va or not vb:
        raise HTTPException(404, "스냅샷을 찾을 수 없습니다.")
    return compare_view(va, vb)


@app.get("/api/snapshots/{sid}")
def snapshot(sid: int, db: Session = Depends(get_db)) -> dict:
    v = snapshot_view(db, sid)
    if v is None:
        raise HTTPException(404, "스냅샷을 찾을 수 없습니다.")
    return v


@app.get("/api/images/{image_hash}")
def image(image_hash: str, db: Session = Depends(get_db)) -> Response:
    row = db.get(Image, image_hash)
    if row is None:
        raise HTTPException(404, "이미지를 찾을 수 없습니다.")
    return Response(get_storage().get(row.storage_key), media_type=row.mime,
                    headers={"Cache-Control": "private, max-age=86400"})


@app.get("/api/admin/adapters")
def adapter_health(db: Session = Depends(get_db)) -> list[dict]:
    out = []
    for a in all_adapters():
        runs = db.scalar(select(func.count()).select_from(CollectJob).where(CollectJob.channel == a.channel)) or 0
        ok = db.scalar(select(func.count()).select_from(CollectJob).where(CollectJob.channel == a.channel,
                                                                           CollectJob.status == "done")) or 0
        last = db.scalar(select(func.max(CollectJob.finished_at)).where(CollectJob.channel == a.channel,
                                                                         CollectJob.status == "done"))
        enabled, why = a.enabled()
        out.append({"channel": a.channel, "label": a.label, "tier": a.tier, "enabled": enabled, "reason": why,
                    "runs": runs, "ok": ok, "last_success": last.isoformat() if last else None})
    return out


@app.get("/")
def index() -> FileResponse:
    return FileResponse(HERE / "static" / "index.html")


app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
