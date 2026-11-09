"""외부 HTTP 호출 공통 규칙.

- 봇임을 밝히는 User-Agent 를 쓴다 (브라우저로 위장하지 않는다)
- robots.txt 가 막은 경로는 요청하지 않는다
- 호스트별 최소 호출 간격을 지킨다
- 차단(403/429)을 우회하려고 재시도하지 않는다 → 그 채널만 '수집 실패'
"""
from __future__ import annotations

import threading
import time
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from searchcosme.config import settings


class Blocked(Exception):
    """robots.txt 금지 또는 사이트의 차단 응답."""


class RateLimiter:
    def __init__(self):
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, host: str, min_interval: float) -> None:
        with self._lock:
            last = self._last.get(host, 0.0)
            delay = last + min_interval - time.monotonic()
            self._last[host] = max(time.monotonic(), last + min_interval)
        if delay > 0:
            time.sleep(delay)


class RobotsGuard:
    def __init__(self, client: httpx.Client):
        self.client = client
        self._cache: dict[str, RobotFileParser | None] = {}
        self._lock = threading.Lock()

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        with self._lock:
            if base not in self._cache:
                rp = RobotFileParser()
                try:
                    r = self.client.get(base + "/robots.txt")
                    if r.status_code == 200:
                        rp.parse(r.text.splitlines())
                    elif r.status_code in (401, 403):
                        rp.disallow_all = True  # robots.txt 자체를 막으면 전부 금지로 본다
                    else:
                        rp.allow_all = True
                except httpx.HTTPError:
                    rp.allow_all = True
                self._cache[base] = rp
            rp = self._cache[base]
        return rp.can_fetch(settings.user_agent, url) if rp else True


class Http:
    def __init__(self, client: httpx.Client | None = None):
        self.client = client or httpx.Client(
            headers={"User-Agent": settings.user_agent}, timeout=settings.http_timeout, follow_redirects=True)
        self.rate = RateLimiter()
        self.robots = RobotsGuard(self.client)

    def get(self, url: str, *, min_interval: float = 1.0, check_robots: bool = True, **kw) -> httpx.Response:
        if check_robots and not self.robots.allowed(url):
            raise Blocked(f"robots.txt 가 수집을 허용하지 않는 주소입니다: {urlsplit(url).path}")
        self.rate.wait(urlsplit(url).netloc, min_interval)
        r = self.client.get(url, **kw)
        if r.status_code in (401, 403, 429):
            raise Blocked(f"사이트가 자동 접근을 막았습니다 (HTTP {r.status_code})")
        r.raise_for_status()
        return r


_http: Http | None = None


def get_http() -> Http:
    global _http
    if _http is None:
        _http = Http()
    return _http
