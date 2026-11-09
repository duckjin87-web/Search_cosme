"""예시 데이터(fixtures/products.json)로 동작하는 어댑터.

실제 채널 수집(화해 크롤링)은 법무 검토 전이라 붙이지 않았다.
같은 인터페이스로 실제 어댑터를 구현해 교체하면 파이프라인은 그대로 쓴다.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.adapters.base import AdapterError
from app.models import Candidate, Product, RawImage, RawPage

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "products.json"


def _norm(s: str) -> str:
    return "".join(s.split()).lower()


class FixtureStore:
    def __init__(self, path: Path = FIXTURE_PATH):
        with open(path, encoding="utf-8") as f:
            self.data = json.load(f)
        self.products = {p["product_key"]: p for p in self.data["products"]}

    def product(self, key: str) -> Product:
        p = self.products[key]
        return Product(p["product_key"], p["brand"], p["name"], p["volume"], p["category"], p.get("barcode"))

    def all_products(self) -> list[Product]:
        return [self.product(k) for k in self.products]

    def listing(self, key: str, channel: str, snapshot: str | None = None) -> dict | None:
        p = self.products[key]
        if snapshot is None:
            return p["listings"].get(channel)
        for h in p.get("history", []):
            if h["collected_at"] == snapshot:
                return h["listings"].get(channel)
        return None

    def history(self, key: str) -> list[str]:
        return [h["collected_at"] for h in self.products[key].get("history", [])]

    def image_fixture(self, image_id: str) -> dict | None:
        for p in self.data["products"]:
            blocks = [p["listings"]] + [h["listings"] for h in p.get("history", [])]
            for listings in blocks:
                for listing in listings.values():
                    for img in listing.get("images", []):
                        if img["id"] == image_id:
                            return {**img, "category": p["category"]}
        return None


def matches(query: str, product: Product) -> bool:
    hay = _norm(f"{product.brand} {product.name} {product.volume}")
    return all(_norm(tok) in hay for tok in query.split() if tok.strip())


class FixtureAdapter:
    def __init__(self, store: FixtureStore, channel: str, label: str, tier: int,
                 delay_sec: float = 0.0, snapshot: str | None = None):
        self.store = store
        self.channel = channel
        self.label = label
        self.tier = tier
        self.min_interval_sec = 1.0
        self.delay_sec = delay_sec
        self.snapshot = snapshot  # None = 현재, 아니면 과거 수집분 재현

    async def search(self, query: str) -> list[Candidate]:
        out = []
        for product in self.store.all_products():
            listing = self.store.listing(product.product_key, self.channel)
            if listing and "error" not in listing and matches(query, product):
                out.append(Candidate(product, self.channel, listing["source_url"], listing["title_raw"]))
        return out

    async def fetch(self, product: Product) -> RawPage | None:
        if self.delay_sec:
            await asyncio.sleep(self.delay_sec)
        listing = self.store.listing(product.product_key, self.channel, self.snapshot)
        if listing is None:
            return None
        if "error" in listing:
            raise AdapterError(listing["error"])
        images = [
            RawImage(img["id"], f"{listing['source_url']}#img={img['id']}", img["w"], img["h"], fixture=img)
            for img in listing.get("images", [])
        ]
        return RawPage(self.channel, listing["source_url"], listing["title_raw"], images, listing.get("detail_text"))
