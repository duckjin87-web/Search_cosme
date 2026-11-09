"""설정은 전부 환경 변수로 받는다. 비밀값(API 키)은 코드·레포에 두지 않는다."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: os.getenv("SC_DATABASE_URL", f"sqlite:///{ROOT / 'var' / 'searchcosme.db'}"))

    # 이미지 저장소: local | s3 (MinIO 포함)
    storage: str = field(default_factory=lambda: os.getenv("SC_STORAGE", "local"))
    storage_dir: str = field(default_factory=lambda: os.getenv("SC_STORAGE_DIR", str(ROOT / "var" / "images")))
    s3_endpoint: str | None = field(default_factory=lambda: os.getenv("SC_S3_ENDPOINT"))
    s3_bucket: str = field(default_factory=lambda: os.getenv("SC_S3_BUCKET", "searchcosme"))
    s3_access_key: str | None = field(default_factory=lambda: os.getenv("SC_S3_ACCESS_KEY"))
    s3_secret_key: str | None = field(default_factory=lambda: os.getenv("SC_S3_SECRET_KEY"))

    # 작업 실행: inline(API 프로세스 안 스레드) | celery(별도 워커)
    queue: str = field(default_factory=lambda: os.getenv("SC_QUEUE", "inline"))
    redis_url: str = field(default_factory=lambda: os.getenv("SC_REDIS_URL", "redis://localhost:6379/0"))

    # 채널
    naver_client_id: str | None = field(default_factory=lambda: os.getenv("NAVER_CLIENT_ID"))
    naver_client_secret: str | None = field(default_factory=lambda: os.getenv("NAVER_CLIENT_SECRET"))
    enable_hwahae: bool = field(default_factory=lambda: _bool("SC_ENABLE_HWAHAE"))
    enable_brand_pages: bool = field(default_factory=lambda: _bool("SC_ENABLE_BRAND_PAGES", True))
    user_agent: str = field(default_factory=lambda: os.getenv(
        "SC_USER_AGENT", "SearchCosmeBot/0.1 (internal label pre-review; respects robots.txt)"))
    http_timeout: float = field(default_factory=lambda: float(os.getenv("SC_HTTP_TIMEOUT", "15")))
    max_images_per_page: int = field(default_factory=lambda: int(os.getenv("SC_MAX_IMAGES_PER_PAGE", "30")))

    # 판독
    ocr_engine: str = field(default_factory=lambda: os.getenv("SC_OCR_ENGINE", "tesseract"))  # tesseract|clova|google
    clova_ocr_url: str | None = field(default_factory=lambda: os.getenv("CLOVA_OCR_URL"))
    clova_ocr_secret: str | None = field(default_factory=lambda: os.getenv("CLOVA_OCR_SECRET"))
    google_vision_key: str | None = field(default_factory=lambda: os.getenv("GOOGLE_VISION_API_KEY"))
    face_classifier: str = field(default_factory=lambda: os.getenv("SC_FACE_CLASSIFIER", "heuristic"))  # heuristic|claude
    claude_model: str = field(default_factory=lambda: os.getenv("SC_CLAUDE_MODEL", "claude-opus-5-5"))

    upload_max_mb: int = field(default_factory=lambda: int(os.getenv("SC_UPLOAD_MAX_MB", "20")))


settings = Settings()
