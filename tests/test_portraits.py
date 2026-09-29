"""头像比对：用随机纹理当"英雄头像"，检查缩放、平移、圆形遮罩、变暗、JPEG 之后仍能认对。"""

import pytest

cv2 = pytest.importorskip("cv2")
import numpy as np

from lolhex.vision import champselect
from lolhex.vision.portraits import IconBank


def _icons(n=40, seed=0):
    rng = np.random.default_rng(seed)
    out = {}
    for i in range(n):
        base = rng.integers(0, 256, (6, 6, 3), dtype=np.uint8)
        out[str(i + 1)] = cv2.resize(base, (120, 120), interpolation=cv2.INTER_CUBIC)
    return out


def _distort(img, size, dx, dy, circle, dark):
    s = cv2.resize(img, (size, size), interpolation=cv2.INTER_AREA)
    pad = size // 6
    canvas = np.full((size + 2 * pad, size + 2 * pad, 3), 20, np.uint8)
    canvas[pad:pad + size, pad:pad + size] = s
    cv2.rectangle(canvas, (pad, pad), (pad + size - 1, pad + size - 1), (60, 170, 200), 2)
    crop = canvas[pad + dy:pad + dy + size, pad + dx:pad + dx + size].copy()
    if circle:
        m = np.zeros(crop.shape[:2], np.uint8)
        cv2.circle(m, (size // 2, size // 2), size // 2, 255, -1)
        crop[m == 0] = 15
    if dark:
        crop = (crop * 0.6).astype(np.uint8)
    _, enc = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 70])
    return cv2.imdecode(enc, cv2.IMREAD_COLOR)


def test_classify_distorted():
    icons = _icons()
    bank = IconBank(icons)
    rng = np.random.default_rng(1)
    wrong = 0
    for hid, img in icons.items():
        crop = _distort(img, int(rng.choice([40, 64, 96])), int(rng.integers(-2, 3)), int(rng.integers(-2, 3)),
                        bool(rng.integers(0, 2)), bool(rng.integers(0, 2)))
        m = bank.classify(crop)
        assert m.hero_id in (hid, None)
        wrong += m.hero_id != hid
    assert wrong <= 2


def test_blank_slot_not_matched():
    bank = IconBank(_icons())
    assert bank.classify(np.full((64, 64, 3), 30, np.uint8)).hero_id is None
    assert bank.classify(np.zeros((4, 4, 3), np.uint8)).hero_id is None


def test_champselect_read(monkeypatch):
    icons = _icons()
    bank = IconBank(icons)
    frame = np.full((900, 1600, 3), 25, np.uint8)
    layout = {"bench": [], "team": []}
    for i, hid in enumerate(["3", "7", "11"]):
        x, y = 500 + i * 70, 20
        frame[y:y + 56, x:x + 56] = cv2.resize(icons[hid], (56, 56), interpolation=cv2.INTER_AREA)
        layout["bench"].append((x / 1600, y / 900, (x + 56) / 1600, (y + 56) / 900))
    layout["bench"].append((1200 / 1600, 20 / 900, 1256 / 1600, 76 / 900))  # 空位
    monkeypatch.setattr(champselect, "LAYOUT", layout)
    got = champselect.read(frame, bank, (100, 50))
    assert [s["hero_id"] for s in got["bench"]] == ["3", "7", "11"]
    assert got["bench"][0]["box"][:2] == (600, 70)
    assert got["team"] == []


def test_team_uses_name_reader_and_gold_name(monkeypatch):
    """队友头像是皮肤图认不出时，用称号文字；金色称号那一行是自己。"""
    bank = IconBank(_icons())
    frame = np.full((1080, 1920, 3), 25, np.uint8)
    frame[176 + 240:206 + 240, 200:300] = (60, 190, 240)  # 第 3 行称号涂成金色（BGR）
    reads = iter([None, "5", "9", None, None])
    got = champselect.read(frame, bank, (0, 0), lambda crop: next(reads))
    assert [(s["slot"], s["hero_id"]) for s in got["team"]] == [(1, "5"), (2, "9")]
    assert got["mine"] == "9"
    assert got["bench"] == []


def test_rank_grade_and_summary():
    from lolhex.engine import rank_grade
    assert [rank_grade(r, 100) for r in (1, 10, 11, 30, 31, 60, 61, 85, 86, 100)] == \
        ["S", "S", "A", "A", "B", "B", "C", "C", "D", "D"]
    assert rank_grade(None, 100) is None
    pytest.importorskip("PySide6")
    from lolhex.ui.overlay import champ_select_summary
    cs = {"mine": "1", "team": [{"hero_id": "1", "name": "韦鲁斯", "win": 0.47, "grade": "C"}],
          "bench": [{"hero_id": "2", "name": "奥拉夫", "win": 0.464, "grade": "C"},
                    {"hero_id": "3", "name": "霞", "win": 0.492, "grade": "B"}]}
    s = champ_select_summary(cs)
    assert s.index("霞") < s.index("奥拉夫")  # 按胜率排序
    assert "↑2.2" in s and "你：韦鲁斯" in s


def test_is_champ_select_marker():
    frame = np.zeros((1080, 1920, 3), np.uint8)
    seen = []

    def rec(text, score=0.99):
        def f(crop):
            seen.append(crop.shape)
            return text, score
        return f
    assert champselect.is_champ_select(frame, rec("可用"))
    assert seen[0][:2] == (36, 80)  # 读的是"可用"那一小块
    assert not champselect.is_champ_select(frame, rec("开始匹配"))
    assert not champselect.is_champ_select(frame, rec("可用", 0.3))


def test_read_cards_two_or_three():
    """开局英雄卡：读到"选择你的英雄"才识别；卡片位置按称号文字定位，二选一/三选一通用。"""
    from lolhex.vision.ocr import TextLine
    frame = np.zeros((1080, 1920, 3), np.uint8)
    names = {"沙漠皇帝": "268", "黑暗之女": "1"}
    lines = [TextLine("黑暗之女", 0.99, (789, 26, 914, 65)), TextLine("沙漠皇帝", 0.99, (142, 25, 266, 65)),
             TextLine("传说", 0.7, (400, 0, 500, 60))]
    cards = champselect.read_cards(frame, lambda c: ("选择你的英雄", 0.99), lambda c: lines, names.get, (10, 0))
    assert [c["hero_id"] for c in cards] == ["268", "1"]
    cx = (cards[0]["box"][0] + cards[0]["box"][2]) / 2
    assert abs(cx - (10 + 430 + 204)) <= 1
    assert champselect.read_cards(frame, lambda c: ("", 0.0), lambda c: lines, names.get) == []


def test_memo_reuses_until_crop_changes():
    calls = []
    memo = champselect.Memo()

    def fn(crop):
        calls.append(1)
        return int(crop.mean())

    a = np.full((40, 40, 3), 100, np.uint8)
    assert memo("k", a, fn) == 100
    assert memo("k", a.copy(), fn) == 100
    a2 = a.copy()
    a2[0, 0] = 101  # 细微噪声：不重算
    memo("k", a2, fn)
    assert len(calls) == 1
    b = np.full((40, 40, 3), 160, np.uint8)  # 换了英雄：重算
    assert memo("k", b, fn) == 160
    assert memo("other", b, fn) == 160  # 不同位置分开缓存
    assert len(calls) == 3


def test_text_spans_skips_thin_borders():
    band = np.full((90, 1060, 3), (60, 30, 40), np.uint8)
    band[:, 330:333] = 200  # 卡片边框细竖线
    for x in (140, 465, 790):  # 三段称号，字间有空隙
        for k in range(4):
            band[30:60, x + k * 32:x + k * 32 + 26] = (190, 210, 225)
    spans = champselect.text_spans(band)
    assert len(spans) == 3
    assert all(a < x < b for (a, b), x in zip(spans, (200, 525, 850)))


def test_clicking_own_panel_keeps_client_foreground(monkeypatch):
    """点右上角浮窗时前台变成浮窗，但客户端还在画面上：选人标注不能消失。"""
    from types import SimpleNamespace
    from lolhex.vision import window as win
    fg = {"h": 111}
    user32 = SimpleNamespace(GetForegroundWindow=lambda: fg["h"], IsIconic=lambda h: 0)
    monkeypatch.setattr(win, "IS_WINDOWS", True)
    monkeypatch.setattr(win, "ctypes", SimpleNamespace(windll=SimpleNamespace(user32=user32)))
    monkeypatch.setattr(win, "_companions", set())
    assert win.is_foreground(111)
    fg["h"] = 222  # 点了自己的浮窗
    assert not win.is_foreground(111)
    win.add_companion(222)
    assert win.is_foreground(111)
    fg["h"] = 333  # 切到别的程序：照常隐藏
    assert not win.is_foreground(111)


def test_memo_retries_unrecognized_until_found():
    """称号淡入时先认不出；画面只差一点（缩略图没超阈值）也要重认，不能一直用"认不出"的缓存。"""
    memo = champselect.Memo()
    results = iter([None, None, "268"])
    calls = []

    def fn(crop):
        calls.append(1)
        return next(results)

    a = np.full((40, 40, 3), 100, np.uint8)
    assert memo("k", a, fn, bool) is None
    assert memo("k", a.copy(), fn, bool) is None
    assert memo("k", a.copy(), fn, bool) == "268"
    assert memo("k", a.copy(), fn, bool) == "268"  # 认出来之后照常复用
    assert len(calls) == 3


def test_read_cards_not_stuck_after_fade_in():
    """先在淡入中途扫到（有标题、认不出名字），画面稳定后再扫一次就要出卡。"""
    from lolhex.vision.ocr import TextLine
    frame = np.zeros((1080, 1920, 3), np.uint8)
    names = {"沙漠皇帝": "268", "黑暗之女": "1"}
    memo = champselect.Memo()
    title = lambda c: ("选择你的英雄", 0.99)
    faded = [TextLine("沙漠", 0.4, (142, 25, 266, 65))]
    shown = [TextLine("黑暗之女", 0.99, (789, 26, 914, 65)), TextLine("沙漠皇帝", 0.99, (142, 25, 266, 65))]
    assert champselect.read_cards(frame, title, lambda c: faded, names.get, memo=memo) == []
    cards = champselect.read_cards(frame, title, lambda c: shown, names.get, memo=memo)
    assert [c["hero_id"] for c in cards] == ["268", "1"]
