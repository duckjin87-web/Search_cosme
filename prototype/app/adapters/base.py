"""채널 어댑터 인터페이스. 새 채널 = 이 인터페이스를 구현한 파일 하나."""
from __future__ import annotations

from typing import Protocol

from app.models import Candidate, Product, RawPage


class AdapterError(Exception):
    """수집 실패. 이 채널만 '수집 실패'로 표시하고 전체 조회는 계속한다."""


class ChannelAdapter(Protocol):
    channel: str            # "hwahae"
    label: str              # "화해"
    tier: int               # 1~4
    min_interval_sec: float # 채널별 호출 간격

    async def search(self, query: str) -> list[Candidate]: ...

    async def fetch(self, product: Product) -> RawPage | None:
        """상품 페이지를 수집한다. 이 채널에 상품이 없으면 None."""
        ...
