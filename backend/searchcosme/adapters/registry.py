from __future__ import annotations

from searchcosme.adapters.naver import NaverShoppingAdapter
from searchcosme.adapters.upload import UploadAdapter
from searchcosme.adapters.webpage import brand_adapter, hwahae_adapter


def all_adapters() -> list:
    """수집 순서 = 티어 순. 사내 업로드(0) → 네이버(1) → 화해(2) → 자사몰(4)."""
    return sorted([UploadAdapter(), NaverShoppingAdapter(), hwahae_adapter(), brand_adapter()], key=lambda a: a.tier)


def adapter(channel: str):
    for a in all_adapters():
        if a.channel == channel:
            return a
    raise KeyError(channel)
