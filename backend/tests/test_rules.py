"""4상태 판정 규칙. 이 규칙이 깨지면 누락 오판이 생긴다."""
from searchcosme.domain import CheckStatus, FaceImage, OcrLine, ProductRef
from searchcosme.rules.extract import extract
from searchcosme.rules.judge import judge_item, load_ruleset

RS = load_ruleset()
ITEMS = {i["id"]: i for i in RS["items"]}
MK = RS["section_markers"]
P = ProductRef(1, "k", "브랜드", "테스트 크림", "50mL", "container")


def img(face, lines):
    return FaceImage("h-" + face, "upload", "upload", 1000, 1000, face, 0.9, "", [OcrLine(t, c) for t, c in lines])


def faces(**kw):
    return {f: kw.get(f, []) for f in ["front", "back", "left", "right", "top", "bottom"]}


def test_ok_from_back():
    r = judge_item(ITEMS["ingredients"], RS, P, faces(back=[img("back", [("전성분: 정제수, 글리세린", 0.95)])]), [])
    assert r.status == CheckStatus.OK and r.value == "정제수, 글리세린"


def test_keyword_tolerates_ocr_spacing():
    r = judge_item(ITEMS["ingredients"], RS, P, faces(back=[img("back", [("전 성 분: 정제수, 글리세린", 0.95)])]), [])
    assert r.status == CheckStatus.OK


def test_face_missing_not_none():
    assert judge_item(ITEMS["ingredients"], RS, P, faces(), []).status == CheckStatus.FACE_MISSING


def test_low_conf_unreadable_not_none():
    r = judge_item(ITEMS["ingredients"], RS, P, faces(back=[img("back", [("전성…", 0.4), ("50mL", 0.9)])]), [])
    assert r.status == CheckStatus.UNREADABLE


def test_none_only_when_fully_read():
    r = judge_item(ITEMS["ingredients"], RS, P, faces(back=[img("back", [("사용방법: 바른다", 0.95)])]), [])
    assert r.status == CheckStatus.NONE


def test_detail_text_fills_and_conflict():
    r = judge_item(ITEMS["ingredients"], RS, P, faces(back=[img("back", [("전성분: 정제수, 글리세린", 0.95)])]),
                   [("hwahae", "전성분: 정제수, 글리세린, 향료")])
    assert r.status == CheckStatus.OK and r.conflict


def test_lot_exp_crimp():
    t = "LOT 2509A12\nEXP 2028.09"
    assert extract(ITEMS["lot_position"], t, "", MK).value == "2509A12"
    assert extract(ITEMS["expiry"], t, "", MK).value == "2028.09"


def test_engine_threshold_present():
    assert RS["thresholds"]["ocr_line_conf_by_engine"]["tesseract"] < RS["thresholds"]["ocr_line_conf"]


def test_different_faces_are_complementary_not_conflict():
    r = judge_item(ITEMS["expiry"], RS, P, faces(back=[img("back", [("사용기한: 별도 표기일까지", 0.95)])],
                                                bottom=[img("bottom", [("EXP 2028.09", 0.95)])]), [])
    assert r.status == CheckStatus.OK and not r.conflict
