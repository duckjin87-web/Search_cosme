"""API 전체 흐름: 제품 등록 → 사내 사진 업로드 → 수집·판정(실제 OCR) → 스냅샷·비교."""
import shutil

import pytest
from fastapi.testclient import TestClient

from imagegen import BACK, BOTTOM, FRONT, SIDE, label
from searchcosme.api import app

pytestmark = pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract 미설치")


def run(c, pid, refresh=False):
    r = c.post(f"/api/products/{pid}/lookups", json={"refresh": refresh}).json()
    assert r["status"] == "collecting"
    body = c.get(f"/api/lookups/{r['lookup_id']}/events").text
    assert '"type": "done"' in body, body
    snaps = c.get(f"/api/products/{pid}/snapshots").json()
    return c.get(f"/api/snapshots/{snaps[0]['snapshot_id']}").json(), body


def status(snap):
    return {c["item_id"]: c["status"] for c in snap["checks"]}


def test_full_flow_with_uploaded_photos():
    with TestClient(app) as c:
        cand = c.post("/api/candidates", json={"query": "수분 장벽 크림"}).json()
        assert any("네이버쇼핑" in n for n in cand["notices"])  # 키 없음 → 건너뜀 안내

        p = c.post("/api/products", json={"brand": "SAMPLECOS", "name": "수분 장벽 크림", "volume": "50mL",
                                          "category": "container"}).json()
        files = [("files", ("front.png", label(FRONT, size=60, width=800), "image/png")),
                 ("files", ("back.png", label(BACK), "image/png")),
                 ("files", ("side.png", label(SIDE, size=40, width=900), "image/png")),
                 ("files", ("bottom.png", label(BOTTOM, size=48, width=900), "image/png"))]
        up = c.post(f"/api/products/{p['id']}/uploads", files=files, data={"face_hint": "", "detail_text": ""}).json()
        assert up["added"] == 4 and not up["rejected"]

        snap, events = run(c, p["id"])
        assert '"channel": "upload"' in events and '"status": "skipped"' in events
        captured = {f["face"] for f in snap["faces"] if f["status"] == "captured"}
        assert {"front", "back", "left", "bottom"} <= captured, snap["faces"]
        st = status(snap)
        assert st["product_name"] == "ok"
        assert st["ingredients"] == "ok"
        assert st["maker"] == "ok"
        assert st["usage_caution"] == "ok"
        assert st["lot_position"] == "ok"
        assert st["recycling"] == "ok"
        assert st["functional"] == "none"  # 기능성 문구 없는 제품
        assert snap["engine_info"]["ocr"] == "tesseract"

        img = snap["faces"][1]["representative"]["image_url"]
        assert c.get(img).headers["content-type"].startswith("image/")

        # 같은 날 다시 누르면 캐시
        assert c.post(f"/api/products/{p['id']}/lookups", json={}).json()["status"] == "cached"


def test_blurred_back_is_unreadable_and_detail_text_fills():
    with TestClient(app) as c:
        p = c.post("/api/products", json={"brand": "SAMPLECOS", "name": "데일리 선크림", "volume": "50mL",
                                          "category": "tube"}).json()
        blurry = label(BACK, size=14, width=520, blur=1.6, scale=0.6)
        files = [("files", ("back.png", blurry, "image/png"))]
        c.post(f"/api/products/{p['id']}/uploads", files=files,
               data={"face_hint": "back", "detail_text": "전성분: 정제수, 징크옥사이드, 글리세린"})
        snap, _ = run(c, p["id"])
        st = status(snap)
        assert st["maker"] == "unreadable"
        assert st["ingredients"] == "ok"  # 상세 텍스트로 보완
        ing = next(x for x in snap["checks"] if x["item_id"] == "ingredients")
        assert ing["source"] == "detail_text" and "상세 텍스트 기준" in ing["note"]
        assert st["recycling"] == "face_missing"


def test_listing_validation_and_compare():
    with TestClient(app) as c:
        p = c.post("/api/products", json={"name": "진정 토너", "volume": "200mL"}).json()
        r = c.post(f"/api/products/{p['id']}/listings", json={"channel": "hwahae", "url": "https://evil.example/x"})
        assert r.status_code == 400
        r = c.post(f"/api/products/{p['id']}/listings", json={"channel": "hwahae", "url": "https://www.hwahae.co.kr/products/1"})
        assert r.status_code == 200 and r.json()["listings"][0]["channel"] == "hwahae"

        c.post(f"/api/products/{p['id']}/uploads", files=[("files", ("f.png", label(["진정 토너", "200mL"], size=60, width=800), "image/png"))],
               data={"face_hint": "front", "detail_text": ""})
        first, ev = run(c, p["id"])
        assert "SC_ENABLE_HWAHAE" in ev  # 화해는 기본 꺼짐 → 건너뜀 사유 표시
        c.post(f"/api/products/{p['id']}/uploads", files=[("files", ("b.png", label(BACK), "image/png"))],
               data={"face_hint": "back", "detail_text": ""})
        second, _ = run(c, p["id"], refresh=True)
        cmp = c.get(f"/api/snapshots/compare?a={first['snapshot_id']}&b={second['snapshot_id']}").json()
        changed = {r["item_id"] for r in cmp["rows"] if r["changed"]}
        assert "ingredients" in changed

        health = {h["channel"]: h for h in c.get("/api/admin/adapters").json()}
        assert health["upload"]["ok"] >= 2 and health["hwahae"]["enabled"] is False
