"""이미지 저장소: 로컬 파일, S3 호환(MinIO). S3 는 moto 로 흉내 낸다."""
import pytest

from searchcosme.storage import LocalStorage


def test_local_storage(tmp_path):
    s = LocalStorage(str(tmp_path))
    s.put("abcd", b"x", "image/png")
    s.put("abcd", b"y", "image/png")  # 같은 해시는 다시 쓰지 않음
    assert s.exists("abcd") and s.get("abcd") == b"x"


def test_s3_storage(monkeypatch):
    moto = pytest.importorskip("moto")
    from searchcosme import config
    from searchcosme.storage import S3Storage
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    new = {"s3_endpoint": None, "s3_bucket": "sc-test", "s3_access_key": "x", "s3_secret_key": "y"}
    old = {k: getattr(config.settings, k) for k in new}
    for k, v in new.items():
        object.__setattr__(config.settings, k, v)  # settings 는 frozen dataclass
    try:
        with moto.mock_aws():
            s = S3Storage()
            s.put("h1", b"img", "image/png")
            assert s.exists("h1") and s.get("h1") == b"img" and not s.exists("nope")
    finally:
        for k, v in old.items():
            object.__setattr__(config.settings, k, v)
