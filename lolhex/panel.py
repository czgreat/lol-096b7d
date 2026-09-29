"""单英雄资料面板：胜率与评级、海克斯全表、出装、加点。数据服务看板和游戏机浮窗共用。"""

from __future__ import annotations

from . import recommend
from .data.store import DataStore


MIN_SHARE = 0.1     # 出装按胜率排之前，先去掉出场不到同类最热门 1/10 的（样本太少，胜率说明不了什么）
MIN_ITEM_GAMES = 1000  # Hexdata 单件装备：至少这么多场才参与排序


def by_win(rows: list[dict], min_games: int = 0) -> list[dict]:
    """有一定出场的里面按胜率从高到低排。出场率缺失时用场次比较。"""
    def share(x):
        return x.get("pick") or x.get("games") or 0
    top = max((share(x) for x in rows), default=0)
    keep = [x for x in rows if x.get("win") is not None and share(x) >= top * MIN_SHARE
            and (x.get("games") or min_games) >= min_games]
    return sorted(keep, key=lambda x: -x["win"])


def hero_panel(store: DataStore, hero_key, k: int = 300) -> dict | None:
    hid = store.resolve_hero(hero_key)
    if not hid:
        return None
    data = store.hero(hid) or {}
    hy = store.huya_hero(hid) or {}
    ag = store.win_data(hid) or {}  # 当前版本 Hexdata 优先，没有就 ARAMGG
    ag_src = ag.get("source") or "aramgg"
    ag_augs = ag.get("augments") or {}
    lag = bool(store.huya.get("patch")) and store.huya.get("patch") != store.static.get("patch")
    drift = store.augment_drift() if lag else {}
    huya_global = store.huya.get("augment_global") or {}

    augs = []
    for a in data.get("augments", []):
        meta = store.augments.get(a["id"], {})
        h = (hy.get("augments") or {}).get(a["id"]) or {}
        x = ag_augs.get(a["id"]) or {}
        dr = drift.get(a["id"])
        changed = None
        if x.get("win") is not None and x.get("games") and ag.get("sample_win") is not None:
            src, win, games = ag_src, x["win"], x["games"]
            d = recommend.smoothed_delta(win, games, ag["sample_win"], k)
        else:
            src, win, games = "huya", h.get("win"), h.get("games")
            d = recommend.smoothed_delta(win, games, hy.get("win"), k)
            if lag and huya_global and a["id"] not in huya_global:
                changed, d = "new", None
            elif dr is not None and abs(dr) >= recommend.DRIFT_DISTRUST:
                changed, d = "reworked", None
            elif dr is not None and abs(dr) >= recommend.DRIFT_CORRECT and d is not None:
                changed, d = "corrected", d + dr
            if win is None:
                src = None
        hd = recommend.smoothed_delta(h.get("win"), h.get("games"), hy.get("win"), k)
        augs.append({**a, "name": meta.get("name", a["id"]), "icon": meta.get("icon"),
                     "desc": meta.get("desc"), "win": win, "games": games, "source": src,
                     "delta": None if d is None else round(d, 2), "drift": dr, "changed": changed,
                     "cn_delta": None if hd is None or src not in ("aramgg", "hexdata") else round(hd, 2),
                     "sample": recommend.sample_level(games)})

    items = store.items

    def item(i, name=None):
        it = items.get(str(i), {})
        return {"id": str(i), "name": it.get("name") or name or str(i), "icon": it.get("icon")}

    b = data.get("builds") or {}
    # 出装都按胜率排（只比有一定出场的）；单件装备有 Hexdata 就用它（腾讯的在部分英雄上口径明显偏离）
    builds = {
        "full": [{**x, "items": [item(i) for i in x["items"]]} for x in by_win(b.get("full", []))],
        "core": [{**x, "items": [item(i) for i in x["items"]]} for x in by_win(b.get("core", []))],
        "first": ([{"item": item(x["id"], x.get("name")), "win": x["win"], "pick": x["pick"], "games": x["games"], "fit": x.get("fit")}
                   for x in by_win(ag["items"], MIN_ITEM_GAMES)[:12]] if ag.get("items")
                  else [{**x, "item": item(x["item"])} for x in by_win(b.get("first", []))]),
        "shoes": [{**x, "item": item(x["item"])} for x in by_win(b.get("shoes", []))],
        "start": [{**x, "items": [item(i) for i in x["items"]]} for x in by_win(b.get("start", []))],
    }
    # 召唤师技能组合（只有 Hexdata 有海斗的；名字和图标用腾讯官方表）
    by_name = {s.get("name"): s for s in store.spells.values()}
    summoners = [{**x, "spells": [{"id": (by_name.get(n) or {}).get("id"), "name": n,
                                   "icon": (by_name.get(n) or {}).get("icon")} for n in x["names"]]}
                 for x in (ag.get("spells") or [])[:3]]
    rank = (store.ranks.get("heroes") or {}).get(hid, {})
    n_heroes = len(store.ranks.get("heroes") or {}) or None
    return {
        "hero": store.heroes.get(hid),
        # 评级：腾讯当天的英雄榜名次 + ARAMGG 的 T1–T5（来自腾讯快照）
        "rank": {**rank, "total": n_heroes, "tier": (store.aramgg_hero(hid) or {}).get("champion_tier") or None},
        "huya": {k2: hy.get(k2) for k2 in ("win", "pick", "games", "tier")},
        "augments": augs, "builds": builds, "skills": data.get("skills", []), "spells": data.get("spells", {}),
        "partners": [{**p, "hero": store.heroes.get(p["hero"], {"id": p["hero"]})}
                     for p in data.get("partners", [])],
        "date": data.get("date"), "patch": store.static.get("patch"),
        "huya_patch": store.huya.get("patch"), "huya_date": store.huya.get("date"),
        "aramgg_patch": ag.get("patch"), "aramgg_date": ag.get("win_date"),
        "win_source": "Hexdata" if ag_src == "hexdata" else "ARAMGG", "summoners": summoners,
    }
