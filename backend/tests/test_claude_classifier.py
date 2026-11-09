"""Claude 면 분류: 응답 파싱과 실패 시 규칙 기반 대체 (API 호출 없이 가짜 클라이언트로)."""
import json
from types import SimpleNamespace

import anthropic
from PIL import Image

from searchcosme.domain import ProductRef
from searchcosme.vision.classify import ClaudeVisionClassifier

P = ProductRef(1, "k", "SAMPLECOS", "수분 장벽 크림", "50mL", "container")


class FakeClient:
    def __init__(self, resp=None, exc=None):
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))
        self.resp, self.exc = resp, exc

    def _create(self, **kw):
        self.calls.append(kw)
        if self.exc:
            raise self.exc
        return self.resp


def resp(stop="end_turn", payload=None):
    return SimpleNamespace(stop_reason=stop, content=[SimpleNamespace(type="text", text=json.dumps(payload or {}))])


def test_parses_structured_output():
    fc = FakeClient(resp(payload={"face": "back", "confidence": 0.93, "reason": "전성분 표가 보임"}))
    face, conf, why = ClaudeVisionClassifier(client=fc).classify(Image.new("RGB", (400, 600)), [], P, None)
    assert (face, conf) == ("back", 0.93) and why.startswith("[Claude]")
    kw = fc.calls[0]
    assert kw["model"] == "claude-opus-5-5"
    assert kw["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in kw["betas"]
    assert kw["output_config"]["format"]["type"] == "json_schema"
    assert kw["messages"][0]["content"][0]["type"] == "image"


def test_refusal_falls_back_to_heuristic():
    fc = FakeClient(resp(stop="refusal"))
    face, conf, why = ClaudeVisionClassifier(client=fc).classify(Image.new("RGB", (400, 600)), [], P, None)
    assert not why.startswith("[Claude]")


def test_connection_error_falls_back():
    import httpx
    exc = anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com"))
    face, conf, why = ClaudeVisionClassifier(client=FakeClient(exc=exc)).classify(Image.new("RGB", (400, 600)), [], P, None)
    assert not why.startswith("[Claude]")
