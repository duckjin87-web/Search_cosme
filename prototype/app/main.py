"""화장품 표시사항 사전검토 — 프로토타입 API 서버.

실행:  uvicorn app.main:app --reload   (prototype/ 디렉터리에서)
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.adapters.fixture import FixtureAdapter, FixtureStore
from app.models import CATEGORY_LABELS, FACE_LABELS
from app.pipeline.collector import Collector, now_kst
from app.pipeline.judge import CHANNEL_LABELS, load_ruleset
from app.pipeline.vision import FixtureFaceClassifier, FixtureOcr
from app.render import render_svg
from app.store import Store
from app.views import STATUS_LABELS, compare_view, product_view, snapshot_view

HERE = Path(__file__).resolve().parent
DB_PATH = os.getenv("SC_DB_PATH", str(HERE.parent / "var" / "search_cosme.db"))
DELAY = float(os.getenv("SC_FIXTURE_DELAY", "1.0"))  # 예시 수집 지연(초 배수). 테스트는 0

fixtures = FixtureStore()
ruleset = load_ruleset()
store = Store(DB_PATH)
collector = Collector(store, ruleset, FixtureFaceClassifier(), FixtureOcr())


def make_adapters(snapshot: str | None = None, delay: float = DELAY) -> list[FixtureAdapter]:
    return [
        FixtureAdapter(fixtures, "naver", "네이버쇼핑", tier=1, delay_sec=0.6 * delay, snapshot=snapshot),
        FixtureAdapter(fixtures, "hwahae", "화해", tier=2, delay_sec=1.8 * delay, snapshot=snapshot),
    ]


async def seed_history() -> None:
    """예시 데이터의 과거 수집분을 스냅샷으로 넣어 기간 조회·비교를 보여준다."""
    for p in fixtures.all_products():
        have = {s["collected_at"] for s in store.list_snapshots(p.product_key)}
        for ts in fixtures.history(p.product_key):
            if ts not in have:
                await collector.collect(p, make_adapters(snapshot=ts, delay=0), lookup_id="seed", collected_at=ts)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await seed_history()
    yield


app = FastAPI(title="화장품 표시사항 사전검토 — 프로토타입", lifespan=lifespan)


class Lookup:
    def __init__(self, product_key: str):
        self.id = uuid.uuid4().hex[:12]
        self.product_key = product_key
        self.events: list[dict] = []
        self.done = False
        self.cond = asyncio.Condition()

    async def emit(self, event: dict) -> None:
        async with self.cond:
            self.events.append(event)
            if event.get("type") in ("done", "error"):
                self.done = True
            self.cond.notify_all()


lookups: dict[str, Lookup] = {}


class LookupRequest(BaseModel):
    query: str = ""
    product_key: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    category: str | None = None
    refresh: bool = False


def image_url(h: str) -> str:
    return f"/api/images/{h}.svg"


async def find_candidates(query: str, category: str | None) -> list[dict]:
    grouped: dict[str, dict] = {}
    for adapter in make_adapters(delay=0):
        for c in await adapter.search(query):
            g = grouped.setdefault(c.product.product_key, {"product": product_view(asdict(c.product)), "listings": []})
            g["listings"].append({"channel": c.channel, "channel_label": adapter.label,
                                  "title_raw": c.title_raw, "source_url": c.source_url})
    out = list(grouped.values())
    if category:
        out = [c for c in out if c["product"]["category"] == category]
    return out


@app.get("/api/meta")
def meta() -> dict:
    return {"ruleset_version": ruleset["version"], "items": ruleset["items"], "thresholds": ruleset["thresholds"],
            "face_labels": FACE_LABELS, "category_labels": CATEGORY_LABELS, "status_labels": STATUS_LABELS,
            "channels": [{"channel": a.channel, "label": a.label, "tier": a.tier} for a in make_adapters()],
            "today": now_kst()[:10]}


@app.post("/api/lookups")
async def create_lookup(req: LookupRequest) -> dict:
    key = req.product_key
    if not key:
        if not req.query.strip():
            raise HTTPException(400, "제품명을 입력하세요.")
        cands = await find_candidates(req.query, req.category)
        if not cands:
            return {"status": "not_found", "query": req.query}
        if len(cands) > 1:
            return {"status": "needs_selection", "query": req.query, "candidates": cands}
        key = cands[0]["product"]["product_key"]
    if key not in fixtures.products:
        raise HTTPException(404, "알 수 없는 제품입니다.")
    product = fixtures.product(key)
    snaps = store.list_snapshots(key, req.date_from, req.date_to)
    today = now_kst()[:10]
    if not req.refresh and any(s["collected_at"][:10] == today for s in store.list_snapshots(key)):
        return {"status": "cached", "product": product_view(asdict(product)), "snapshots": snaps}

    lookup = Lookup(key)
    lookups[lookup.id] = lookup

    async def run() -> None:
        try:
            await collector.collect(product, make_adapters(), emit=lookup.emit, lookup_id=lookup.id)
        except Exception as e:  # pragma: no cover
            await lookup.emit({"type": "error", "message": str(e)})

    asyncio.create_task(run())
    return {"status": "collecting", "lookup_id": lookup.id, "product": product_view(asdict(product)),
            "snapshots": snaps}


@app.get("/api/lookups/{lookup_id}/events")
async def lookup_events(lookup_id: str) -> StreamingResponse:
    lookup = lookups.get(lookup_id)
    if lookup is None:
        raise HTTPException(404, "조회를 찾을 수 없습니다.")

    async def stream():
        i = 0
        while True:
            async with lookup.cond:
                await lookup.cond.wait_for(lambda: len(lookup.events) > i or lookup.done)
                batch = lookup.events[i:]
            for ev in batch:
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
            i += len(batch)
            if lookup.done and i >= len(lookup.events):
                break

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/api/products/{product_key}/snapshots")
def product_snapshots(product_key: str, date_from: str | None = None, date_to: str | None = None) -> list[dict]:
    return store.list_snapshots(product_key, date_from, date_to)


@app.get("/api/snapshots/compare")
def compare(a: int, b: int) -> dict:
    sa, sb = store.get_snapshot(a), store.get_snapshot(b)
    if not sa or not sb:
        raise HTTPException(404, "스냅샷을 찾을 수 없습니다.")
    return compare_view(snapshot_view(sa, image_url), snapshot_view(sb, image_url))


@app.get("/api/snapshots/{snapshot_id}")
def snapshot(snapshot_id: int) -> dict:
    snap = store.get_snapshot(snapshot_id)
    if not snap:
        raise HTTPException(404, "스냅샷을 찾을 수 없습니다.")
    return snapshot_view(snap, image_url)


@app.get("/api/images/{image_hash}.svg")
def image(image_hash: str) -> Response:
    row = store.image(image_hash)
    fx = fixtures.image_fixture(row["image_ref"]) if row else None
    if not fx:
        raise HTTPException(404, "이미지를 찾을 수 없습니다.")
    return Response(render_svg(fx, ruleset["thresholds"]["ocr_line_conf"]), media_type="image/svg+xml")


@app.get("/api/admin/adapters")
def adapter_health() -> list[dict]:
    return [{**r, "label": CHANNEL_LABELS.get(r["channel"], r["channel"])} for r in store.adapter_health()]


@app.get("/")
def index() -> FileResponse:
    return FileResponse(HERE / "static" / "index.html")


app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
