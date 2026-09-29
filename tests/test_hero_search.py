"""手动搜英雄：别名、玩家叫法、拼音缩写都能搜到。"""
import os

import pytest


def test_resolve_hero_by_alias(store):
    assert store.resolve_hero("提百万") == "17"      # 玩家叫法（Hexdata）
    assert store.resolve_hero("快乐风男") == "157"
    assert store.resolve_hero("tm") == "17"          # 腾讯关键词里的拼音缩写
    assert store.resolve_hero("火女") == "1"
    assert store.resolve_hero("托儿所") == "157"     # 网上常见外号（hero_nicknames.json）
    assert store.resolve_hero("蘑菇") == "17"
    assert store.resolve_hero("龙王") == "136"
    assert store.resolve_hero("快乐风") == "157"     # 外号的一部分
    assert store.resolve_hero("提莫") == "17"        # 原有的名字照旧
    assert store.resolve_hero("不存在的英雄") is None


def test_completer_matches_aliases(store):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from lolhex.ui.herosearch import hero_completer
    app = QApplication.instance() or QApplication([])
    comp, names = hero_completer(store)

    def hits(prefix):
        comp.setCompletionPrefix(prefix)
        m = comp.completionModel()
        return [names[m.index(i, 0).data(Qt.UserRole)] for i in range(m.rowCount())]

    assert "17" in hits("提百万")
    assert "157" in hits("快乐风男")
    assert "17" in hits("xjch")
    assert "157" in hits("托儿所")
    assert hits("提莫") == ["17"]
    m = comp.completionModel()
    comp.setCompletionPrefix("提百万")
    assert m.index(0, 0).data() == "提莫 迅捷斥候（提百万、蘑菇、提莫队长）"  # 下拉里显示的文字
    assert app is not None
