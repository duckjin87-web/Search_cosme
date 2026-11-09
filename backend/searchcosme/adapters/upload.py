"""사내 업로드: 실물·샘플을 직접 찍은 사진과 상세 텍스트. 약관 문제가 없고 6면을 다 채울 수 있다."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from searchcosme.domain import Candidate, ProductRef, RawImage, RawPage
from searchcosme.models import Image, Upload
from searchcosme.storage import get_storage


class UploadAdapter:
    channel = "upload"
    label = "사내 업로드"
    tier = 0
    searchable = False

    def enabled(self) -> tuple[bool, str]:
        return True, ""

    def search(self, query: str) -> list[Candidate]:
        return []

    def fetch(self, db: Session, product: ProductRef) -> RawPage | None:
        rows = db.execute(select(Upload, Image).join(Image, Image.hash == Upload.image_hash)
                          .where(Upload.product_id == product.id).order_by(Upload.uploaded_at)).all()
        if not rows:
            return None
        storage = get_storage()
        images = [RawImage(storage.get(img.storage_key), f"upload:{up.id}", None,
                           hint=f"face:{up.face_hint}" if up.face_hint else "upload") for up, img in rows]
        texts = sorted({up.detail_text for up, _ in rows if up.detail_text})
        return RawPage(self.channel, "upload", "사내 업로드", images, "\n".join(texts) or None)
