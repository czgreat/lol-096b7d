"""Hexdata（hexdata.com.cn）单英雄数据快照：国服海克斯大乱斗，样本约为 ARAMGG 的 7 倍。

只读数据目录里人工放进去的快照文件（<store>/hexdata.json），**不联网抓取**：
Hexdata 的数据表只在登录页，robots.txt 不允许自动访问 /api/、/data/。文件只自用，不进仓库。

快照格式（整理脚本生成）：{"patch": "16.19", "heroes": {"17": {"name", "fetched_at",
"augments": [...], "decisions": [...], "items": [...], "spells": [...]}}}，表内字段是 CSV 原样字符串。
"""

from __future__ import annotations

import statistics


def _f(s) -> float | None:
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _gain(s: str | None) -> float | None:
    """"+7.8%" → 0.078；"+<0.01%" 这种截断值返回 None。"""
    v = None if not s or "<" in s else _f(s.strip().rstrip("%"))
    return None if v is None else v / 100


def parse_hero(raw: dict, patch: str | None) -> dict:
    """→ 与 ARAMGG 单英雄数据同样的结构（面板和推荐可以直接换用），另带 items / spells。"""
    augs, bases = {}, []
    for r in raw.get("augments") or []:
        win, games = _f(r.get("win_rate")), int(_f(r.get("games")) or 0)
        if not r.get("augment_id") or win is None or not games:
            continue
        augs[str(r["augment_id"])] = {"win": win, "games": games}
        g = _gain(r.get("win_rate_gain"))
        if g is not None and games >= 5000:
            bases.append(win - g)
    # 英雄基准胜率：Hexdata 的收益 = 海克斯胜率 − 英雄胜率，用大样本海克斯反推
    if bases:
        base = statistics.median(bases)
    else:
        tot = sum(a["games"] for a in augs.values())
        base = sum(a["win"] * a["games"] for a in augs.values()) / tot if tot else None
    items = []
    for r in raw.get("items") or []:
        win, games = _f(r.get("win_rate")), int(_f(r.get("games")) or 0)
        if r.get("item_id") and win is not None and games:
            items.append({"id": str(r["item_id"]), "name": (r.get("item_name") or "").split("/")[0] or None, "win": win, "pick": _f(r.get("pick_rate")),
                          "games": games, "fit": _f(r.get("item_fit"))})
    items.sort(key=lambda x: -(x["pick"] or 0))
    spells = []
    for r in raw.get("spells") or []:
        names = [n.strip() for n in (r.get("spell_combo") or "").split("+") if n.strip()]
        if len(names) == 2 and _f(r.get("pick_rate")) is not None:
            spells.append({"names": names, "pick": _f(r.get("pick_rate")), "win": _f(r.get("win_rate")),
                           "games": int(_f(r.get("games")) or 0)})
    spells.sort(key=lambda x: -x["pick"])
    return {"source": "hexdata", "patch": patch, "win_date": (raw.get("fetched_at") or "")[:10] or None,
            "sample_win": base, "sample_games": sum(a["games"] for a in augs.values()),
            "augments": augs, "items": items, "spells": spells}


def parse(raw: dict) -> dict[str, dict]:
    patch = raw.get("patch")
    return {str(hid): parse_hero(h, patch) for hid, h in (raw.get("heroes") or {}).items()}
