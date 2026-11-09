"""이미지 저장소. 레포·DB 밖에 두고 해시를 키로 쓴다 (같은 이미지는 한 번만 저장)."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

from searchcosme.config import settings


class Storage(Protocol):
    def put(self, key: str, data: bytes, mime: str) -> None: ...
    def get(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...


class LocalStorage:
    def __init__(self, root: str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / key

    def put(self, key: str, data: bytes, mime: str) -> None:
        p = self._path(key)
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()


class S3Storage:
    """MinIO 등 S3 호환 저장소."""

    def __init__(self):
        import boto3
        self.bucket = settings.s3_bucket
        self.s3 = boto3.client("s3", endpoint_url=settings.s3_endpoint, aws_access_key_id=settings.s3_access_key,
                               aws_secret_access_key=settings.s3_secret_key)
        try:
            self.s3.head_bucket(Bucket=self.bucket)
        except Exception:
            self.s3.create_bucket(Bucket=self.bucket)

    def put(self, key: str, data: bytes, mime: str) -> None:
        if not self.exists(key):
            self.s3.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=mime)

    def get(self, key: str) -> bytes:
        return self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def exists(self, key: str) -> bool:
        try:
            self.s3.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False


_storage: Storage | None = None


def get_storage() -> Storage:
    global _storage
    if _storage is None:
        _storage = S3Storage() if settings.storage == "s3" else LocalStorage(settings.storage_dir)
    return _storage
