"""정적 데모 HTML 한 장 만들기 (서버 없이 열어보는 용도).

서버와 같은 파이프라인을 예시 데이터에 돌려 결과를 JSON으로 굳히고,
같은 화면(index.html / style.css / app.js)에 끼워 넣는다.

    python scripts/build_static.py  →  dist/demo.html
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["SC_DB_PATH"] = ":memory:"
os.environ["SC_FIXTURE_DELAY"] = "0"

from app import main as m  # noqa: E402
from app.render import render_svg  # noqa: E402
from app.views import compare_view, snapshot_view  # noqa: E402

PRECOLLECTED = ["samplecos-barrier-cream-50ml"]  # 처음 열 때 '캐시에 있음'으로 보여줄 제품


def data_uri(h: str) -> str:
    row = m.store.image(h)
    fx = m.fixtures.image_fixture(row["image_ref"])
    svg = render_svg(fx, m.ruleset["thresholds"]["ocr_line_conf"])
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


async def build() -> dict:
    await m.seed_history()
    events: dict[str, list[dict]] = {}
    today_ids: dict[str, int] = {}
    for p in m.fixtures.all_products():
        evs: list[dict] = []
        today_ids[p.product_key] = await m.collector.collect(p, m.make_adapters(delay=0), emit=evs.append,
                                                             lookup_id="static")
        events[p.product_key] = evs

    catalog, snapshots, views, compares = [], {}, {}, {}
    for p in m.fixtures.all_products():
        cands = await m.find_candidates(p.name, None)
        catalog.extend(c for c in cands if c["product"]["product_key"] == p.product_key)
        snaps = m.store.list_snapshots(p.product_key)
        snapshots[p.product_key] = [{**s, "pending": s["snapshot_id"] == today_ids[p.product_key]} for s in snaps]
        for s in snaps:
            views[s["snapshot_id"]] = snapshot_view(m.store.get_snapshot(s["snapshot_id"]), data_uri)
        for newer, older in zip(snaps, snaps[1:]):
            compares[f"{older['snapshot_id']}-{newer['snapshot_id']}"] = compare_view(
                views[older["snapshot_id"]], views[newer["snapshot_id"]])

    return {"meta": m.meta(), "catalog": catalog, "snapshots": snapshots, "views": views,
            "compares": compares, "events": events, "precollected": PRECOLLECTED}


def main() -> None:
    data = asyncio.run(build())
    static = ROOT / "app" / "static"
    html = (static / "index.html").read_text(encoding="utf-8")
    css = (static / "style.css").read_text(encoding="utf-8")
    js = (static / "app.js").read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = html.replace('<link rel="stylesheet" href="/static/style.css">', "<style>\n" + css + "\n</style>")
    html = html.replace('<script src="/static/app.js"></script>',
                        "<script>window.STATIC_DATA = " + payload + ";</script>\n<script>\n" + js + "\n</script>")
    html = html.replace("프로토타입 · 예시 데이터", "정적 데모 · 예시 데이터")
    out = ROOT / "dist" / "demo.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
