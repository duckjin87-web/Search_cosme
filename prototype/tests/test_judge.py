"""4상태 판정 규칙 테스트. 이 규칙이 깨지면 누락 오판이 생긴다."""
from app.models import CheckStatus, FaceImage, OcrLine, Product
from app.pipeline.judge import judge_item, load_ruleset

RS = load_ruleset()
ITEMS = {i["id"]: i for i in RS["items"]}
P = Product("k", "브랜드", "테스트 크림", "50mL", "container")


def img(face, lines, channel="hwahae"):
    return FaceImage("h-" + face, channel, "https://example.com", 1000, 1000, face, 0.9,
                     [OcrLine(t, c) for t, c in lines])


def faces(**kw):
    return {f: kw.get(f, []) for f in ["front", "back", "left", "right", "top", "bottom"]}


def test_ok_from_back_ocr():
    r = judge_item(ITEMS["ingredients"], RS, P, faces(back=[img("back", [("전성분: 정제수, 글리세린", 0.95)])]), [])
    assert r.status == CheckStatus.OK
    assert r.value == "정제수, 글리세린"
    assert r.source == "ocr"


def test_face_missing_is_not_none():
    r = judge_item(ITEMS["ingredients"], RS, P, faces(), [])
    assert r.status == CheckStatus.FACE_MISSING


def test_low_confidence_is_unreadable_not_none():
    r = judge_item(ITEMS["ingredients"], RS, P,
                   faces(back=[img("back", [("전성…: 정제…", 0.45), ("50mL", 0.9)])]), [])
    assert r.status == CheckStatus.UNREADABLE
    assert "0.45" in r.note


def test_empty_ocr_is_unreadable():
    r = judge_item(ITEMS["maker"], RS, P, faces(back=[img("back", [])]), [])
    assert r.status == CheckStatus.UNREADABLE


def test_none_only_when_fully_read():
    r = judge_item(ITEMS["ingredients"], RS, P, faces(back=[img("back", [("사용방법: 바른다", 0.95)])]), [])
    assert r.status == CheckStatus.NONE


def test_keyword_in_low_conf_line_does_not_count():
    r = judge_item(ITEMS["ingredients"], RS, P, faces(back=[img("back", [("전성분: 정제수", 0.5)])]), [])
    assert r.status == CheckStatus.UNREADABLE


def test_detail_text_fills_when_back_unreadable():
    r = judge_item(ITEMS["ingredients"], RS, P, faces(back=[img("back", [("전…", 0.4)])]),
                   [("hwahae", "전성분: 정제수, 글리세린")])
    assert r.status == CheckStatus.OK
    assert r.source == "detail_text"
    assert "상세 텍스트 기준" in r.note


def test_conflict_keeps_both_values():
    r = judge_item(ITEMS["ingredients"], RS, P, faces(back=[img("back", [("전성분: 정제수, 글리세린", 0.95)])]),
                   [("hwahae", "전성분: 정제수, 글리세린, 향료")])
    assert r.status == CheckStatus.OK
    assert r.conflict is True
    assert {o.source for o in r.observations} == {"ocr", "detail_text"}


def test_same_value_different_spacing_is_not_conflict():
    r = judge_item(ITEMS["volume"], RS, P, faces(front=[img("front", [("50 mL", 0.95)])]),
                   [("hwahae", "용량: 50mL")])
    assert r.conflict is False


def test_partial_groups_are_not_ok():
    r = judge_item(ITEMS["usage_caution"], RS, P, faces(back=[img("back", [("사용방법: 바른다", 0.95)])]), [])
    assert r.status == CheckStatus.NONE
    assert "주의사항 미확인" in r.note


def test_detail_text_not_used_for_position_items():
    # 제조번호 위치는 실물 면에서만 확인한다
    r = judge_item(ITEMS["lot_position"], RS, P, faces(), [("hwahae", "제조번호: 하단 표기")])
    assert r.status == CheckStatus.FACE_MISSING


def test_functional_none_mentions_condition():
    r = judge_item(ITEMS["functional"], RS, P, faces(front=[img("front", [("테스트 크림", 0.95)])]), [])
    assert r.status == CheckStatus.NONE
    assert "기능성화장품이 아니면" in r.note
