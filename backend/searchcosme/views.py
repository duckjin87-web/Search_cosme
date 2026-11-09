"""API 응답 모양."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from searchcosme.domain import CATEGORY_LABELS, CHANNEL_LABELS, FACE_LABELS, FACES
from searchcosme.models import Check, Face, Image, Listing, Product, Snapshot, Upload
from searchcosme.rules.extract import normalize

STATUS_LABELS = {"ok": "있음", "none": "없음", "unreadable": "판독불가", "face_missing": "면 미확보"}


def product_view(db: Session, p: Product) -> dict:
    listings = db.scalars(select(Listing).where(Listing.product_id == p.id).order_by(Listing.channel)).all()
    uploads = db.scalars(select(Upload).where(Upload.product_id == p.id)).all()
    return {
        "id": p.id, "product_key": p.product_key, "brand": p.brand, "name": p.name, "volume": p.volume,
        "barcode": p.barcode, "category": p.category, "category_label": CATEGORY_LABELS.get(p.category, p.category),
        "listings": [{"id": l.id, "channel": l.channel, "channel_label": CHANNEL_LABELS.get(l.channel, l.channel),
                      "source_url": l.source_url, "title_raw": l.title_raw} for l in listings],
        "uploads": [{"id": u.id, "image_url": f"/api/images/{u.image_hash}", "face_hint": u.face_hint,
                     "uploaded_at": u.uploaded_at.isoformat()} for u in uploads],
    }


def snapshot_list(db: Session, product_id: int, date_from: str | None, date_to: str | None) -> list[dict]:
    q = select(Snapshot).where(Snapshot.product_id == product_id).order_by(Snapshot.collected_at.desc())
    out = []
    for s in db.scalars(q).all():
        day = s.collected_at.isoformat()[:10]
        if (date_from and day < date_from) or (date_to and day > date_to):
            continue
        out.append({"snapshot_id": s.id, "collected_at": s.collected_at.isoformat(), "ruleset_version": s.ruleset_version})
    return out


def snapshot_view(db: Session, sid: int) -> dict | None:
    s = db.get(Snapshot, sid)
    if s is None:
        return None
    p = db.get(Product, s.product_id)
    labels = FACE_LABELS.get(p.category, FACE_LABELS["container"])
    rows = db.execute(select(Face, Image).join(Image, Image.hash == Face.image_hash)
                      .where(Face.snapshot_id == sid).order_by(Face.is_representative.desc(), Face.id)).all()

    def img(f: Face, i: Image) -> dict:
        return {"image_hash": f.image_hash, "channel": f.channel, "channel_label": CHANNEL_LABELS.get(f.channel, f.channel),
                "source_url": f.source_url, "width": i.width, "height": i.height, "face_conf": f.face_conf,
                "face_reason": f.face_reason, "ocr_confidence": f.ocr_conf, "ocr_lines": f.ocr_lines,
                "image_url": f"/api/images/{f.image_hash}", "sliced": i.parent_hash is not None}

    faces = []
    for face in FACES:
        imgs = [img(f, i) for f, i in rows if f.face == face]
        faces.append({"face": face, "label": labels[face], "status": "captured" if imgs else "missing",
                      "representative": imgs[0] if imgs else None, "extra": imgs[1:]})
    checks = []
    for c in db.scalars(select(Check).where(Check.snapshot_id == sid).order_by(Check.id)).all():
        checks.append({
            "item_id": c.item_id, "item_name": c.item_name, "basis": c.basis, "faces": c.faces,
            "face_labels": [labels.get(f, f) for f in c.faces], "status": c.status,
            "status_label": STATUS_LABELS[c.status], "value": c.value, "source": c.source, "conflict": c.conflict,
            "note": c.note,
            "values": [{"source": v.source, "channel": v.channel, "channel_label": CHANNEL_LABELS.get(v.channel, v.channel),
                        "face": v.face, "face_label": labels.get(v.face) if v.face else None, "value_raw": v.value_raw}
                       for v in c.values],
        })
    summary = {k: sum(1 for c in checks if c["status"] == k) for k in STATUS_LABELS}
    summary["conflict"] = sum(1 for c in checks if c["conflict"])
    return {
        "snapshot_id": s.id, "collected_at": s.collected_at.isoformat(), "ruleset_version": s.ruleset_version,
        "dedup_count": s.dedup_count, "engine_info": s.engine_info, "channels": s.channels,
        "product": product_view(db, p), "faces": faces,
        "unclassified": [img(f, i) for f, i in rows if f.face == "unclassified"],
        "checks": checks, "summary": summary,
    }


def compare_view(a: dict, b: dict) -> dict:
    by_a = {c["item_id"]: c for c in a["checks"]}
    rows = []
    for cb in b["checks"]:
        ca = by_a.get(cb["item_id"])
        if ca is None:
            continue
        changed = ca["status"] != cb["status"] or normalize(ca["value"] or "") != normalize(cb["value"] or "")
        rows.append({"item_id": cb["item_id"], "item_name": cb["item_name"], "changed": changed,
                     "before": {"status": ca["status"], "status_label": ca["status_label"], "value": ca["value"]},
                     "after": {"status": cb["status"], "status_label": cb["status_label"], "value": cb["value"]}})
    return {"before": {"snapshot_id": a["snapshot_id"], "collected_at": a["collected_at"]},
            "after": {"snapshot_id": b["snapshot_id"], "collected_at": b["collected_at"]},
            "ruleset_changed": a["ruleset_version"] != b["ruleset_version"],
            "rows": rows, "changed_count": sum(r["changed"] for r in rows)}
