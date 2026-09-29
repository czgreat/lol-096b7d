"""手动选英雄的搜索补全：名字、称号之外，别名和拼音缩写也能搜到（提百万、快乐风男、tm）。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QCompleter


def hero_completer(store, parent=None) -> tuple[QCompleter, dict[str, str]]:
    """返回补全器和 {补全文字: 英雄 id}。下拉里显示"提莫 迅捷斥候（提百万）"，
    按包含关系匹配名字、称号、中文别名和英文/拼音关键词。"""
    rows, names = [], {}
    for hid, h in store.heroes.items():
        base = f"{h['name']} {h['nick']}"
        extra = [t for t in store.hero_terms(hid) if t.lower() not in base.lower()]
        cn = [t for t in extra if not t.isascii()]
        key = " ".join([base, *extra])
        names[key] = hid
        rows.append((base + (f"（{'、'.join(cn)}）" if cn else ""), key))
    comp = QCompleter(parent)
    model = QStandardItemModel(comp)  # 挂在补全器上，免得函数返回后被回收
    for display, key in sorted(rows):
        item = QStandardItem(display)
        item.setData(key, Qt.UserRole)
        model.appendRow(item)
    comp.setModel(model)
    comp.setCompletionRole(Qt.UserRole)
    comp.setCaseSensitivity(Qt.CaseInsensitive)
    comp.setFilterMode(Qt.MatchContains)
    return comp, names
