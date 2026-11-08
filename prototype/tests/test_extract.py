from app.pipeline.extract import extract, normalize
from app.pipeline.judge import load_ruleset

RS = load_ruleset()
ITEMS = {i["id"]: i for i in RS["items"]}
MK = RS["section_markers"]


def test_section_stops_at_next_marker():
    t = "전성분: 정제수, 글리세린\n사용방법: 바른다"
    assert extract(ITEMS["ingredients"], t, "", MK).value == "정제수, 글리세린"


def test_volume_with_bonus():
    assert extract(ITEMS["volume"], "50mL + 15mL", "", MK).value == "50mL+15mL"


def test_single_line_items_stop_at_newline():
    t = "분리배출 용기: PP\n8800000000017"
    assert extract(ITEMS["recycling"], t, "", MK).value == "용기: PP"


def test_lot_and_exp_on_same_crimp():
    t = "LOT 2509A12\nEXP 2028.09"
    assert extract(ITEMS["lot_position"], t, "", MK).value == "2509A12"
    assert extract(ITEMS["expiry"], t, "", MK).value == "2028.09"


def test_normalize():
    assert normalize("정제수, 글리세린") == normalize("정제수,글리세린")


def test_ingredients_stop_before_functional_line():
    t = "전성분: 정제수, 1,2-헥산다이올\n기능성: 자외선 차단"
    assert extract(ITEMS["ingredients"], t, "", MK).value == "정제수, 1,2-헥산다이올"
