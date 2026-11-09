"""채널 어댑터 인터페이스. 새 채널 = 이 인터페이스를 구현한 파일 하나 + registry 등록."""
from __future__ import annotations

from typing import Protocol

from sqlalchemy.orm import Session

from searchcosme.domain import Candidate, ProductRef, RawPage


class AdapterError(Exception):
    """이 채널만 '수집 실패'로 표시하고 전체 조회는 계속한다."""


class AdapterSkipped(Exception):
    """설정이 없거나 비활성이라 이번 조회에서 건너뜀."""


class ChannelAdapter(Protocol):
    channel: str
    label: str
    tier: int
    searchable: bool  # 제품명으로 후보를 찾을 수 있는가 (False 면 URL 등록·업로드로만 연결)

    def enabled(self) -> tuple[bool, str]: ...

    def search(self, query: str) -> list[Candidate]: ...

    def fetch(self, db: Session, product: ProductRef) -> RawPage | None:
        """상품 자료 수집. 이 채널에 연결된 자료가 없으면 None."""
        ...
