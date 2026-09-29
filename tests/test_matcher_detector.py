import pytest
from conftest import fixture

from lolhex.data.tencent import parse_kiwi_augments
from lolhex.vision.matcher import NameMatcher, normalize

AUGS = parse_kiwi_augments(fixture("tencent_kiwi_augments.json"))
NAMES = {k: v["name"] for k, v in AUGS.items()}


def test_normalize():
    assert normalize("质变：棱彩阶") == normalize("质变:棱彩阶") == "质变棱彩阶"


def test_matcher_tolerates_ocr_noise():
    m = NameMatcher(NAMES)
    assert m.match("虚幻武器")[0] == "1029"
    assert m.match("质变:棱彩阶")[0] == "1238"
    assert m.match("炽燃利忌")[0] == "2128"          # 一个字识别错
    assert m.match("获得1个随机强化符文。")[0] is None  # 描述文字不应命中
    assert m.match("A")[0] is None


rapidocr = pytest.importorskip("rapidocr")
synth = pytest.importorskip("synth")
if not synth.fonts_available():
    pytest.skip("没有中文字体，跳过合成画面测试", allow_module_level=True)


@pytest.fixture(scope="module")
def detector():
    from lolhex.vision.detector import AugmentDetector
    return AugmentDetector(NameMatcher(NAMES))


def names(offer):
    return [NAMES.get(s) if s else None for s in offer.slots]


@pytest.mark.parametrize("size", [(3840, 2160), (1920, 1080)])
def test_full_scan_calibrates_and_strip_tracks_reroll(detector, size):
    from lolhex.vision.window import Rect
    detector.calibration = None
    offer = detector.scan_full(synth.render_offer(["质变：棱彩阶", "炽燃利息", "虚幻武器"], size))
    assert names(offer) == ["质变：棱彩阶", "炽燃利息", "虚幻武器"]
    assert detector.calibrated_for(*size)

    win = Rect(0, 0, *size)
    sr = detector.strip_rect(win)
    frame = synth.render_offer(["泰坦的坚决", "炽燃利息", "虚幻武器"], size, seed=3)
    offer2 = detector.check_strip(frame[sr.top:sr.bottom, sr.left:sr.right], win)
    assert names(offer2) == ["泰坦的坚决", "炽燃利息", "虚幻武器"]

    empty = synth.render_offer([None, None, None], size, seed=4)
    assert detector.check_strip(empty[sr.top:sr.bottom, sr.left:sr.right], win) is None

    # 点击位置映射到卡片列
    b = detector.calibration.pixel_boxes(*size)[2]
    assert detector.column_of((b[0] + b[2]) // 2, b[3] + 50, win) == 2


def test_two_cards_are_placed_by_symmetry(detector):
    size = (3840, 2160)
    assert names(detector.scan_full(synth.render_offer(["炽燃利息", None, "虚幻武器"], size))) == ["炽燃利息", None, "虚幻武器"]
    assert names(detector.scan_full(synth.render_offer([None, "炽燃利息", "虚幻武器"], size))) == [None, "炽燃利息", "虚幻武器"]


def test_no_offer_on_plain_screen(detector):
    assert detector.scan_full(synth.render_offer([None, None, None], (3840, 2160), seed=9)) is None


@pytest.mark.parametrize("size", [(3840, 2160), (1920, 1080), (2560, 1600)])
def test_default_calibration_reads_first_offer(tmp_path, size):
    """没校准过也能直接走轻量检查；三张都对上后存成本机校准。"""
    from lolhex.vision.detector import AugmentDetector
    from lolhex.vision.window import Rect
    det = AugmentDetector(NameMatcher(NAMES), tmp_path / "calibration.json")
    det.ensure_calibration(*size)
    assert det.calibrated_for(*size) and not det.confirmed_for(*size)
    win = Rect(0, 0, *size)
    sr = det.strip_rect(win)
    frame = synth.render_offer(["质变：棱彩阶", "炽燃利息", "虚幻武器"], size)
    offer = det.check_strip(frame[sr.top:sr.bottom, sr.left:sr.right], win)
    assert names(offer) == ["质变：棱彩阶", "炽燃利息", "虚幻武器"]
    assert det.confirmed_for(*size)
    assert AugmentDetector(NameMatcher(NAMES), tmp_path / "calibration.json").confirmed_for(*size)


def test_old_default_interval_migrates(tmp_path):
    import json
    from lolhex.config import Settings
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"scan_interval_ms": 700, "show_winrate": False}), encoding="utf-8")
    s = Settings.load(p)
    assert s.scan_interval_ms == 300 and s.show_winrate is False
    assert json.loads(p.read_text(encoding="utf-8"))["scan_interval_ms"] == 300
    p.write_text(json.dumps({"scan_interval_ms": 500}), encoding="utf-8")
    assert Settings.load(p).scan_interval_ms == 500  # 手改过的不动
