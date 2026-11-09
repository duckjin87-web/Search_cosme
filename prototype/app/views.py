"""API 응답 모양. 서버와 정적 데모 빌드가 같이 쓴다."""
from __future__ import annotations

from app.models import CATEGORY_LABELS, FACE_LABELS, FACES
from app.pipeline.extract import normalize
from app.pipeline.judge import CHANNEL_LABELS

STATUS_LABELS = {"ok": "있음", "none": "없음", "unreadable": "판독불가", "face_missing": "면 미확보"}


def product_view(p: dict) -> dict:
    return {**p, "category_label": CATEGORY_LABELS[p["category"]]}


def snapshot_view(snap: dict, image_url) -> dict:
    cat = snap["product"]["category"]
    labels = FACE_LABELS[cat]

    def img(row: dict) -> dict:
        return {
            "image_hash": row["image_hash"], "channel": row["channel"],
            "channel_label": CHANNEL_LABELS.get(row["channel"], row["channel"]),
            "source_url": row["source_url"], "width": row["width"], "height": row["height"],
            "face_conf": row["face_conf"], "ocr_confidence": row["ocr_confidence"],
            "image_url": image_url(row["image_hash"]),
        }

    faces = []
    for f in FACES:
        rows = [r for r in snap["faces"] if r["face"] == f and r["status"] == "captured"]
        faces.append({
            "face": f, "label": labels[f], "status": "captured" if rows else "missing",
            "representative": img(rows[0]) if rows else None,
            "extra": [img(r) for r in rows[1:]],
        })
    unclassified = [img(r) for r in snap["faces"] if r["face"] == "unclassified"]

    checks = []
    for c in snap["checks"]:
        checks.append({
            **c, "status_label": STATUS_LABELS[c["status"]],
            "face_labels": [labels[f] for f in c["faces"]],
            "values": [{**v, "channel_label": CHANNEL_LABELS.get(v["channel"], v["channel"]),
                        "face_label": labels.get(v["face"]) if v["face"] else None} for v in c["values"]],
        })
    summary = {k: sum(1 for c in checks if c["status"] == k) for k in STATUS_LABELS}
    summary["conflict"] = sum(1 for c in checks if c["conflict"])
    return {
        "snapshot_id": snap["snapshot_id"], "collected_at": snap["collected_at"],
        "ruleset_version": snap["ruleset_version"], "dedup_count": snap["dedup_count"],
        "product": product_view(snap["product"]), "channels": snap["channels"],
        "faces": faces, "unclassified": unclassified, "checks": checks, "summary": summary,
    }


def compare_view(a: dict, b: dict) -> dict:
    """a = 기준(이전), b = 비교(이후)."""
    by_a = {c["item_id"]: c for c in a["checks"]}
    rows = []
    for cb in b["checks"]:
        ca = by_a.get(cb["item_id"])
        if ca is None:
            continue
        value_changed = (ca["value"] or "") != (cb["value"] or "") and \
            normalize(ca["value"] or "") != normalize(cb["value"] or "")
        status_changed = ca["status"] != cb["status"]
        rows.append({
            "item_id": cb["item_id"], "item_name": cb["item_name"],
            "before": {"status": ca["status"], "status_label": STATUS_LABELS[ca["status"]], "value": ca["value"]},
            "after": {"status": cb["status"], "status_label": STATUS_LABELS[cb["status"]], "value": cb["value"]},
            "changed": value_changed or status_changed,
            "ruleset_changed": a["ruleset_version"] != b["ruleset_version"],
        })
    return {"before": {"snapshot_id": a["snapshot_id"], "collected_at": a["collected_at"]},
            "after": {"snapshot_id": b["snapshot_id"], "collected_at": b["collected_at"]},
            "rows": rows, "changed_count": sum(r["changed"] for r in rows)}
