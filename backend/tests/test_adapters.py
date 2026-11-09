"""채널 어댑터. 실제 사이트 대신 httpx MockTransport 로 응답을 흉내 낸다."""
import uuid

import httpx
import pytest

from searchcosme import http as schttp
from searchcosme.adapters.base import AdapterError, AdapterSkipped
from searchcosme.adapters.naver import NaverShoppingAdapter, split_title
from searchcosme.adapters.webpage import WebpageAdapter, parse_product_page
from searchcosme.db import SessionLocal, init_db
from searchcosme.domain import ProductRef
from searchcosme.models import Listing, Product

PAGE = """<html><head><title>샘플 크림</title>
<meta property="og:title" content="샘플코스 수분 장벽 크림 50mL">
<meta property="og:image" content="/img/main.jpg">
<script type="application/ld+json">{"@type":"Product","name":"수분 장벽 크림","image":["https://shop.example/img/back.jpg"]}</script>
<script id="__NEXT_DATA__" type="application/json">{"props":{"product":{"ingredients":[{"korean":"정제수"},{"korean":"글리세린"},{"korean":"판테놀"}]}}}</script>
</head><body><nav>전성분 메뉴</nav><img src="/icons/logo.png"><img src="/img/detail1.jpg" width="800">
<div><h3>사용방법</h3><p>적당량을 바릅니다.</p><h3>용량</h3><p>50mL</p></div></body></html>"""


def test_parse_product_page():
    out = parse_product_page(PAGE, "https://shop.example/p/1")
    assert out["title"] == "샘플코스 수분 장벽 크림 50mL"
    assert "https://shop.example/img/main.jpg" in out["images"]
    assert "https://shop.example/img/back.jpg" in out["images"]
    assert "https://shop.example/img/detail1.jpg" in out["images"]
    assert not any("logo" in u for u in out["images"])
    assert "전성분: 정제수, 글리세린, 판테놀" in out["detail_text"]
    assert "사용방법" in out["detail_text"]


@pytest.fixture
def mock_http():
    calls = []

    def install(handler):
        def wrapped(request):
            calls.append(str(request.url))
            return handler(request)
        schttp._http = schttp.Http(httpx.Client(transport=httpx.MockTransport(wrapped)))
        return calls
    yield install
    schttp._http = None


@pytest.fixture
def product():
    init_db()
    with SessionLocal() as db:
        p = Product(product_key=f"k-{uuid.uuid4().hex}", brand="샘플코스", name="수분 장벽 크림", volume="50mL", category="container")
        db.add(p)
        db.commit()
        yield db, ProductRef(p.id, p.product_key, p.brand, p.name, p.volume, p.category)


def test_webpage_respects_robots(mock_http, product):
    db, ref = product
    calls = mock_http(lambda r: httpx.Response(200, text="User-agent: *\nDisallow: /goods-view") if r.url.path == "/robots.txt"
                      else httpx.Response(200, text=PAGE))
    db.add(Listing(product_id=ref.id, channel="brand", source_url="https://shop.example/goods-view/1"))
    db.commit()
    with pytest.raises(AdapterError, match="robots.txt"):
        WebpageAdapter("brand", "자사몰", 4, enabled_flag=True, disabled_reason="").fetch(db, ref)
    assert not any("goods-view" in c for c in calls)


def test_webpage_block_is_not_retried(mock_http, product):
    db, ref = product
    calls = mock_http(lambda r: httpx.Response(404) if r.url.path == "/robots.txt" else httpx.Response(403))
    db.add(Listing(product_id=ref.id, channel="hwahae", source_url="https://www.hwahae.co.kr/products/1"))
    db.commit()
    with pytest.raises(AdapterError, match="HTTP 403"):
        WebpageAdapter("hwahae", "화해", 2, enabled_flag=True, disabled_reason="").fetch(db, ref)
    assert sum("/products/1" in c for c in calls) == 1


def test_webpage_fetch_ok(mock_http, product):
    db, ref = product
    from imagegen import BACK, label
    png = label(BACK)

    def handler(r):
        if r.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        if r.url.path.startswith("/img/"):
            return httpx.Response(200, content=png, headers={"content-type": "image/png"})
        return httpx.Response(200, text=PAGE, headers={"content-type": "text/html"})
    mock_http(handler)
    db.add(Listing(product_id=ref.id, channel="brand", source_url="https://shop.example/p/1"))
    db.commit()
    page = WebpageAdapter("brand", "자사몰", 4, enabled_flag=True, disabled_reason="").fetch(db, ref)
    assert len(page.images) == 3 and "전성분" in page.detail_text


def test_hwahae_url_check():
    a = WebpageAdapter("hwahae", "화해", 2, enabled_flag=True, disabled_reason="", allowed_hosts=("www.hwahae.co.kr",))
    with pytest.raises(ValueError):
        a.check_url("https://evil.example/x")


def test_naver_without_keys_is_skipped():
    with pytest.raises(AdapterSkipped):
        NaverShoppingAdapter().search("크림")


def test_naver_search(monkeypatch, mock_http):
    from searchcosme import config
    object.__setattr__(config.settings, "naver_client_id", "id")
    object.__setattr__(config.settings, "naver_client_secret", "secret")
    seen = {}

    def handler(r):
        seen["headers"] = dict(r.headers)
        return httpx.Response(200, json={"items": [{
            "title": "[샘플코스] <b>수분</b> 장벽 크림 50ml", "link": "https://search.shopping.naver.com/catalog/1",
            "image": "https://shopping-phinf.pstatic.net/a.jpg", "productId": "123", "brand": "샘플코스",
            "category1": "화장품/미용", "category3": "크림"}]})
    mock_http(handler)
    try:
        c = NaverShoppingAdapter().search("수분 장벽 크림")[0]
    finally:
        object.__setattr__(config.settings, "naver_client_id", None)
        object.__setattr__(config.settings, "naver_client_secret", None)
    assert seen["headers"]["x-naver-client-id"] == "id"
    assert (c.brand, c.name, c.volume, c.category_guess) == ("샘플코스", "수분 장벽 크림", "50ml", "container")


def test_naver_auth_error(mock_http):
    from searchcosme import config
    object.__setattr__(config.settings, "naver_client_id", "bad")
    object.__setattr__(config.settings, "naver_client_secret", "bad")
    mock_http(lambda r: httpx.Response(401, json={"errorMessage": "Authentication failed"}))
    try:
        with pytest.raises(AdapterError):
            NaverShoppingAdapter().search("크림")
    finally:
        object.__setattr__(config.settings, "naver_client_id", None)
        object.__setattr__(config.settings, "naver_client_secret", None)


def test_split_title():
    assert split_title("데일리 선크림 SPF50+ 50ml (1+1)", "") == ("데일리 선크림 SPF50+", "50ml")
