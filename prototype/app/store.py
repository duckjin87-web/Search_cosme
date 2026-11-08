"""스냅샷 저장소. 운영은 PostgreSQL, 프로토타입은 SQLite (스키마는 제안서 6절과 같다)."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from app.models import CheckResult, FaceImage, Product

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
  product_key TEXT PRIMARY KEY, brand TEXT, name TEXT, volume TEXT, barcode TEXT, category TEXT);
CREATE TABLE IF NOT EXISTS snapshots (
  snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT, product_key TEXT, collected_at TEXT,
  ruleset_version TEXT, channels_json TEXT, dedup_count INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS images (
  image_hash TEXT PRIMARY KEY, image_ref TEXT, channel TEXT, source_url TEXT,
  width INTEGER, height INTEGER, first_seen_at TEXT);
CREATE TABLE IF NOT EXISTS faces (
  snapshot_id INTEGER, face TEXT, status TEXT, image_hash TEXT, channel TEXT,
  face_conf REAL, ocr_confidence REAL, is_representative INTEGER);
CREATE TABLE IF NOT EXISTS checks (
  check_id INTEGER PRIMARY KEY AUTOINCREMENT, snapshot_id INTEGER, item_id TEXT, item_name TEXT,
  basis TEXT, faces_json TEXT, status TEXT, value TEXT, source TEXT, conflict INTEGER, note TEXT);
CREATE TABLE IF NOT EXISTS check_values (
  check_id INTEGER, source TEXT, channel TEXT, face TEXT, value_raw TEXT);
CREATE TABLE IF NOT EXISTS collect_jobs (
  job_id INTEGER PRIMARY KEY AUTOINCREMENT, lookup_id TEXT, channel TEXT, status TEXT,
  message TEXT, started_at TEXT, finished_at TEXT);
"""


class Store:
    def __init__(self, path: str | Path = ":memory:"):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock:
            self.db.executescript(SCHEMA)

    def _x(self, sql: str, args=()) -> sqlite3.Cursor:
        with self.lock:
            cur = self.db.execute(sql, args)
            self.db.commit()
            return cur

    def _q(self, sql: str, args=()) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    # products ---------------------------------------------------------
    def upsert_product(self, p: Product) -> None:
        self._x("INSERT OR REPLACE INTO products VALUES (?,?,?,?,?,?)",
                (p.product_key, p.brand, p.name, p.volume, p.barcode, p.category))

    def get_product(self, key: str) -> dict | None:
        rows = self._q("SELECT * FROM products WHERE product_key=?", (key,))
        return rows[0] if rows else None

    # snapshots --------------------------------------------------------
    def save_snapshot(self, product: Product, collected_at: str, ruleset_version: str,
                      channels: list[dict], faces: dict[str, list[FaceImage]],
                      unclassified: list[FaceImage], checks: list[CheckResult],
                      dedup_count: int, image_refs: dict[str, str]) -> int:
        self.upsert_product(product)
        sid = self._x(
            "INSERT INTO snapshots (product_key, collected_at, ruleset_version, channels_json, dedup_count) "
            "VALUES (?,?,?,?,?)",
            (product.product_key, collected_at, ruleset_version, json.dumps(channels, ensure_ascii=False), dedup_count),
        ).lastrowid
        all_imgs = [i for imgs in faces.values() for i in imgs] + unclassified
        for img in all_imgs:
            self._x("INSERT OR IGNORE INTO images VALUES (?,?,?,?,?,?,?)",
                    (img.image_hash, image_refs.get(img.image_hash), img.channel, img.source_url,
                     img.width, img.height, collected_at))
        for face, imgs in faces.items():
            if not imgs:
                self._x("INSERT INTO faces VALUES (?,?,?,?,?,?,?,?)", (sid, face, "missing", None, None, None, None, 0))
            for i, img in enumerate(imgs):
                self._x("INSERT INTO faces VALUES (?,?,?,?,?,?,?,?)",
                        (sid, face, "captured", img.image_hash, img.channel, img.face_conf, img.ocr_conf, int(i == 0)))
        for img in unclassified:
            self._x("INSERT INTO faces VALUES (?,?,?,?,?,?,?,?)",
                    (sid, "unclassified", "captured", img.image_hash, img.channel, img.face_conf, img.ocr_conf, 0))
        for c in checks:
            cid = self._x(
                "INSERT INTO checks (snapshot_id,item_id,item_name,basis,faces_json,status,value,source,conflict,note) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (sid, c.item_id, c.item_name, c.basis, json.dumps(c.faces), c.status.value, c.value, c.source,
                 int(c.conflict), c.note),
            ).lastrowid
            for o in c.observations:
                self._x("INSERT INTO check_values VALUES (?,?,?,?,?)", (cid, o.source, o.channel, o.face, o.value))
        return sid

    def list_snapshots(self, product_key: str, date_from: str | None = None, date_to: str | None = None) -> list[dict]:
        sql = "SELECT snapshot_id, product_key, collected_at, ruleset_version FROM snapshots WHERE product_key=?"
        args: list = [product_key]
        if date_from:
            sql += " AND substr(collected_at,1,10) >= ?"
            args.append(date_from)
        if date_to:
            sql += " AND substr(collected_at,1,10) <= ?"
            args.append(date_to)
        return self._q(sql + " ORDER BY collected_at DESC", args)

    def get_snapshot(self, sid: int) -> dict | None:
        rows = self._q("SELECT * FROM snapshots WHERE snapshot_id=?", (sid,))
        if not rows:
            return None
        snap = rows[0]
        snap["channels"] = json.loads(snap.pop("channels_json"))
        snap["product"] = self.get_product(snap["product_key"])
        snap["faces"] = self._q(
            "SELECT f.*, i.source_url, i.width, i.height FROM faces f LEFT JOIN images i USING(image_hash) "
            "WHERE snapshot_id=? ORDER BY is_representative DESC", (sid,))
        checks = self._q("SELECT * FROM checks WHERE snapshot_id=? ORDER BY check_id", (sid,))
        for c in checks:
            c["faces"] = json.loads(c.pop("faces_json"))
            c["conflict"] = bool(c["conflict"])
            c["values"] = self._q("SELECT source, channel, face, value_raw FROM check_values WHERE check_id=?",
                                  (c["check_id"],))
        snap["checks"] = checks
        return snap

    def image(self, image_hash: str) -> dict | None:
        rows = self._q("SELECT * FROM images WHERE image_hash=?", (image_hash,))
        return rows[0] if rows else None

    # collect jobs -----------------------------------------------------
    def log_job(self, lookup_id: str, channel: str, status: str, message: str, started_at: str, finished_at: str) -> None:
        self._x("INSERT INTO collect_jobs (lookup_id, channel, status, message, started_at, finished_at) "
                "VALUES (?,?,?,?,?,?)", (lookup_id, channel, status, message, started_at, finished_at))

    def adapter_health(self) -> list[dict]:
        return self._q(
            "SELECT channel, COUNT(*) AS runs, SUM(status='done') AS ok, "
            "MAX(CASE WHEN status='done' THEN finished_at END) AS last_success "
            "FROM collect_jobs GROUP BY channel")
