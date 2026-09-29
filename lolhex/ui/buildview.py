"""出装、召唤师技能的富文本（主窗口和浮窗共用）：装备和召唤师技能都只放图标。
图标还没下载好时先显示名字，下载完 IconCache.version 变化后界面重新渲染。"""

from __future__ import annotations

GRAY = "#8b93a7"


def _pct(x) -> str:
    return "—" if x is None else f"{x * 100:.1f}%"


def _img(path: str, size: int) -> str:
    return f'<img src="{path}" width="{size}" height="{size}" align="middle">'


def item(icons, it: dict, size: int) -> str:
    """装备：只放图标（还没下载好时临时用名字）。"""
    p = icons.local("item", it.get("id"), it.get("icon")) if icons else None
    return _img(p, size) if p else (it.get("name") or it.get("id") or "")


def spell_pair(icons, row: dict, size: int) -> str:
    """召唤师技能组合：只放图标（没下载好时临时用名字）。"""
    out = []
    for s in row.get("spells") or []:
        p = icons.local("spell", s.get("id"), s.get("icon")) if icons and s.get("id") else None
        out.append(_img(p, size) if p else s.get("name", ""))
    return "&nbsp;".join(out)


def lines(d: dict, icons, show_win: bool, size: int = 24, compact: bool = False) -> list[str]:
    """出装相关的几行：召唤师技能（Hexdata）、核心三件、鞋子、出门装。compact=浮窗（各取第一套、图标小一号）。"""
    b = d.get("builds") or {}
    wr = (lambda x: f" <span style='color:{GRAY}'>{_pct(x)}</span>") if show_win else (lambda x: "")
    out = []
    sums = (d.get("summoners") or [])[: 2 if compact else 3]
    if sums and compact:
        out.append("<b>召唤师技能</b>　" + "　　".join(
            spell_pair(icons, s, size) + f" <span style='color:{GRAY}'>{_pct(s.get('pick'))}</span>" for s in sums))
    elif sums:
        out.append("<b>召唤师技能</b>")
        out.extend(f"　{spell_pair(icons, s, size)} <span style='color:{GRAY}'>出场 {_pct(s.get('pick'))}"
                   + (f" · 胜率 {_pct(s.get('win'))}" if show_win else "") + "</span>" for s in sums)

    def core(c):
        return " → ".join(item(icons, x, size) for x in c.get("items") or []) + wr(c.get("win"))
    cores = b.get("core") or []
    if cores and compact:
        out.append("<b>核心</b>　" + core(cores[0]))
    elif cores:
        out.append("<b>核心三件</b>")
        out.extend("　" + core(c) for c in cores[:3])
    shoes = (b.get("shoes") or [])[: 1 if compact else 2]
    if shoes:
        out.append("<b>鞋子</b>　" + "　".join(item(icons, x["item"], size) + wr(x.get("win")) for x in shoes))
    if b.get("start"):
        s = b["start"][0]
        out.append("<b>出门装</b>　" + " + ".join(item(icons, x, size) for x in s.get("items") or []) + wr(s.get("win")))
    return out
