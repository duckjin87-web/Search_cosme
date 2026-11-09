"""Tier 1 · 네이버 쇼핑 검색 API (공식).

https://developers.naver.com/docs/serviceapi/search/shopping/shopping.md
API 는 상품당 대표 이미지 1장과 판매 링크만 준다 → 제품 후보 식별 + 전면 이미지 용도.
"""
from __future__ import annotations

import html
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from searchcosme.adapters.base import AdapterError, AdapterSkipped
from searchcosme.config import settings
from searchcosme.domain import Candidate, ProductRef, RawImage, RawPage
from searchcosme.http import Blocked, get_http
from searchcosme.models import Listing
from searchcosme.rules.extract import VOLUME_RE

API = "https://openapi.naver.com/v1/search/shop.json"
TUBE_HINTS = ("튜브", "선크림", "선블록", "선젤", "클렌징폼", "폼클렌저", "클렌징 폼", "핸드크림", "필링젤", "아이크림")


def clean_title(t: str) -> str:
    t = html.unescape(re.sub(r"</?b>", "", t))
    return re.sub(r"\s+", " ", t).strip()


def split_title(title: str, brand: str) -> tuple[str, str]:
    """'[브랜드] 수분 크림 50ml 1+1' → (이름, 용량)"""
    m = VOLUME_RE.search(title)
    volume = m.group(0).replace(" ", "") if m else ""
    name = title
    name = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", name)
    if m:
        name = name.replace(m.group(0), " ")
    if brand:
        name = re.sub(rf"^\s*{re.escape(brand)}\s*", "", name)
    name = re.sub(r"\s+", " ", name).strip(" -/,")
    return name or title, volume


def guess_category(*texts: str) -> str:
    joined = " ".join(texts)
    return "tube" if any(h in joined for h in TUBE_HINTS) else "container"


class NaverShoppingAdapter:
    channel = "naver"
    label = "네이버쇼핑"
    tier = 1
    searchable = True

    def enabled(self) -> tuple[bool, str]:
        if settings.naver_client_id and settings.naver_client_secret:
            return True, ""
        return False, "NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 미설정"

    def _headers(self) -> dict:
        return {"X-Naver-Client-Id": settings.naver_client_id or "",
                "X-Naver-Client-Secret": settings.naver_client_secret or ""}

    def search(self, query: str, display: int = 20) -> list[Candidate]:
        ok, why = self.enabled()
        if not ok:
            raise AdapterSkipped(why)
        try:
            r = get_http().get(API, params={"query": query, "display": display, "sort": "sim"},
                               headers=self._headers(), check_robots=False, min_interval=0.2)
        except Blocked as e:
            raise AdapterError(f"네이버 API 인증 실패 또는 차단: {e}") from e
        except Exception as e:
            raise AdapterError(f"네이버 API 호출 실패: {e}") from e
        out = []
        for it in r.json().get("items", []):
            title = clean_title(it.get("title", ""))
            brand = it.get("brand") or it.get("maker") or ""
            name, volume = split_title(title, brand)
            cats = " ".join(it.get(f"category{i}", "") for i in range(1, 5))
            out.append(Candidate(
                channel=self.channel, brand=brand, name=name, volume=volume,
                category_guess=guess_category(title, cats), title_raw=title,
                source_url=it.get("link", ""), image_url=it.get("image"), external_id=str(it.get("productId", "")),
                extra={"mall": it.get("mallName"), "lprice": it.get("lprice"), "category": cats.strip()},
            ))
        return out

    def fetch(self, db: Session, product: ProductRef) -> RawPage | None:
        rows = db.scalars(select(Listing).where(Listing.product_id == product.id, Listing.channel == self.channel)).all()
        if not rows:
            return None
        images, notes = [], []
        for row in rows[:3]:
            if not row.image_url:
                continue
            try:
                r = get_http().get(row.image_url, check_robots=False, min_interval=0.3)
                images.append(RawImage(r.content, row.source_url, row.image_url))
            except Exception as e:
                notes.append(f"이미지 내려받기 실패: {e}")
        if not images and notes:
            raise AdapterError(notes[0])
        return RawPage(self.channel, rows[0].source_url, rows[0].title_raw, images, None, notes)
