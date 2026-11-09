"""상품 페이지 범용 파서 (Tier 2 화해 · Tier 4 브랜드 자사몰).

검색으로 상품을 찾지 않는다. 사용자가 등록한 상품 페이지 URL 만 연다.
robots.txt 를 지키고, 차단 응답이 오면 우회하지 않고 '수집 실패'로 남긴다.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from searchcosme.adapters.base import AdapterError
from searchcosme.config import settings
from searchcosme.domain import Candidate, ProductRef, RawImage, RawPage
from searchcosme.http import Blocked, get_http
from searchcosme.models import Listing

KEYWORDS = ("전성분", "성분", "사용방법", "사용법", "주의사항", "제조업자", "제조원", "책임판매업자", "판매원",
            "용량", "내용량", "사용기한", "개봉 후", "기능성", "분리배출")
SKIP_IMG = re.compile(r"(logo|icon|sprite|banner|badge|btn|button|arrow|blank|spacer|tracking|pixel)", re.I)


def _jsonld_products(soup: BeautifulSoup) -> list[dict]:
    out = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            d = stack.pop()
            if isinstance(d, dict):
                if d.get("@type") in ("Product", ["Product"]):
                    out.append(d)
                stack.extend(v for v in d.values() if isinstance(v, (dict, list)))
            elif isinstance(d, list):
                stack.extend(d)
    return out


def _ingredients_from_json(data, out: list[str], depth: int = 0) -> None:
    """SPA 페이지의 내장 JSON(__NEXT_DATA__ 등)에서 'ingredient' 키의 목록을 찾는다."""
    if depth > 12:
        return
    if isinstance(data, dict):
        for k, v in data.items():
            if "ingredient" in k.lower() and isinstance(v, list) and v:
                names = []
                for x in v:
                    if isinstance(x, str):
                        names.append(x)
                    elif isinstance(x, dict):
                        n = x.get("korean") or x.get("name") or x.get("nameKo") or x.get("ko")
                        if isinstance(n, str):
                            names.append(n)
                if len(names) >= 3:
                    out.append("전성분: " + ", ".join(names))
            else:
                _ingredients_from_json(v, out, depth + 1)
    elif isinstance(data, list):
        for x in data[:500]:
            _ingredients_from_json(x, out, depth + 1)


def parse_product_page(html: str, base_url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    title = ""
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        title = og["content"].strip()
    elif soup.title and soup.title.string:
        title = soup.title.string.strip()

    images: list[str] = []
    for p in _jsonld_products(soup):
        img = p.get("image")
        for u in (img if isinstance(img, list) else [img]):
            if isinstance(u, dict):
                u = u.get("url")
            if isinstance(u, str):
                images.append(u)
    for meta in soup.find_all("meta", property="og:image"):
        if meta.get("content"):
            images.append(meta["content"])

    ingredient_lines: list[str] = []
    for tag in soup.find_all("script"):
        txt = tag.string or ""
        if tag.get("id") == "__NEXT_DATA__" or tag.get("type") == "application/json":
            try:
                _ingredients_from_json(json.loads(txt), ingredient_lines)
            except (json.JSONDecodeError, TypeError):
                pass

    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "svg"]):
        tag.decompose()
    for img in soup.find_all("img"):
        src = img.get("data-src") or img.get("data-original") or img.get("src") or ""
        if not src or src.startswith("data:") or src.endswith(".svg") or SKIP_IMG.search(src):
            continue
        w = img.get("width")
        if w and str(w).isdigit() and int(w) < 120:
            continue
        images.append(src)

    lines = [re.sub(r"\s+", " ", l).strip() for l in soup.get_text("\n").splitlines()]
    lines = [l for l in lines if l]
    keep: list[str] = []
    i = 0
    while i < len(lines):
        if any(k in lines[i] for k in KEYWORDS):
            keep.extend(lines[i:i + 4])
            i += 4
        else:
            i += 1
    detail = "\n".join(ingredient_lines + keep)[:20000] or None

    seen, uniq = set(), []
    for u in images:
        full = urljoin(base_url, u)
        if full not in seen and full.startswith("http"):
            seen.add(full)
            uniq.append(full)
    return {"title": title, "images": uniq, "detail_text": detail}


class WebpageAdapter:
    searchable = False

    def __init__(self, channel: str, label: str, tier: int, *, enabled_flag: bool,
                 disabled_reason: str, allowed_hosts: tuple[str, ...] | None = None):
        self.channel, self.label, self.tier = channel, label, tier
        self._enabled = enabled_flag
        self._disabled_reason = disabled_reason
        self.allowed_hosts = allowed_hosts

    def enabled(self) -> tuple[bool, str]:
        return (True, "") if self._enabled else (False, self._disabled_reason)

    def search(self, query: str) -> list[Candidate]:
        return []

    def check_url(self, url: str) -> None:
        host = urlsplit(url).netloc.lower()
        if self.allowed_hosts and host not in self.allowed_hosts:
            raise ValueError(f"{self.label} 주소가 아닙니다: {host}")

    def fetch(self, db: Session, product: ProductRef) -> RawPage | None:
        rows = db.scalars(select(Listing).where(Listing.product_id == product.id, Listing.channel == self.channel)).all()
        if not rows:
            return None
        images: list[RawImage] = []
        details, notes = [], []
        title = rows[0].title_raw
        for row in rows:
            try:
                page = get_http().get(row.source_url, min_interval=2.0)
            except Blocked as e:
                raise AdapterError(str(e)) from e
            except httpx.HTTPStatusError as e:
                raise AdapterError(f"페이지를 열지 못했습니다 (HTTP {e.response.status_code})") from e
            except httpx.HTTPError as e:
                raise AdapterError(f"페이지에 연결하지 못했습니다 ({type(e).__name__})") from e
            parsed = parse_product_page(page.text, str(page.url))
            title = parsed["title"] or title
            if parsed["detail_text"]:
                details.append(parsed["detail_text"])
            for url in parsed["images"][: settings.max_images_per_page]:
                try:
                    r = get_http().get(url, min_interval=0.5)
                    if r.headers.get("content-type", "").startswith("image/"):
                        images.append(RawImage(r.content, row.source_url, url))
                except Blocked as e:
                    notes.append(f"이미지 차단: {e}")
                except Exception as e:
                    notes.append(f"이미지 실패: {e}")
        return RawPage(self.channel, rows[0].source_url, title, images, "\n".join(details) or None, notes)


def hwahae_adapter() -> WebpageAdapter:
    return WebpageAdapter(
        "hwahae", "화해", 2, enabled_flag=settings.enable_hwahae,
        disabled_reason="비활성 (SC_ENABLE_HWAHAE). 화해는 자동 접근을 차단하고 있어 제휴·허가 후 켭니다",
        allowed_hosts=("www.hwahae.co.kr", "hwahae.co.kr"))


def brand_adapter() -> WebpageAdapter:
    return WebpageAdapter("brand", "브랜드 자사몰", 4, enabled_flag=settings.enable_brand_pages,
                          disabled_reason="비활성 (SC_ENABLE_BRAND_PAGES)")
