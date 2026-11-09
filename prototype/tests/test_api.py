from fastapi.testclient import TestClient

from app.main import app


def test_lookup_flow():
    with TestClient(app) as c:
        r = c.post("/api/lookups", json={"query": "수분 장벽 크림"}).json()
        assert r["status"] == "needs_selection"
        assert len(r["candidates"]) == 2

        r = c.post("/api/lookups", json={"product_key": "samplecos-daily-sun-50ml"}).json()
        assert r["status"] == "collecting"
        body = c.get(f"/api/lookups/{r['lookup_id']}/events").text
        assert '"type": "done"' in body

        r = c.post("/api/lookups", json={"product_key": "samplecos-daily-sun-50ml"}).json()
        assert r["status"] == "cached"
        snap = c.get(f"/api/snapshots/{r['snapshots'][0]['snapshot_id']}").json()
        status = {ch["item_id"]: ch["status"] for ch in snap["checks"]}
        assert status["ingredients"] == "ok"
        assert status["maker"] == "unreadable"
        assert status["recycling"] == "face_missing"
        assert snap["unclassified"]

        img = snap["faces"][0]["representative"]["image_url"]
        assert c.get(img).headers["content-type"].startswith("image/svg")


def test_failed_channel_does_not_stop_lookup():
    with TestClient(app) as c:
        r = c.post("/api/lookups", json={"product_key": "samplecos-calming-toner-200ml", "refresh": True}).json()
        body = c.get(f"/api/lookups/{r['lookup_id']}/events").text
        assert '"status": "failed"' in body
        assert '"type": "done"' in body


def test_history_compare():
    with TestClient(app) as c:
        r = c.post("/api/lookups", json={"product_key": "samplecos-barrier-cream-50ml", "refresh": True}).json()
        c.get(f"/api/lookups/{r['lookup_id']}/events")
        snaps = c.get("/api/products/samplecos-barrier-cream-50ml/snapshots").json()
        assert len(snaps) >= 2
        cmp = c.get(f"/api/snapshots/compare?a={snaps[-1]['snapshot_id']}&b={snaps[0]['snapshot_id']}").json()
        changed = {row["item_id"] for row in cmp["rows"] if row["changed"]}
        assert "ingredients" in changed
        assert "recycling" in changed
