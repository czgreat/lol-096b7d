"""Hexdata 快照：当前版本优先于 ARAMGG；版本对不上就退回；掷骰狂人不当首选。"""

import json

from lolhex.data import hexdata
from lolhex.panel import hero_panel
from lolhex.recommend import evaluate


def _snap(patch="16.19"):
    # 提莫：英雄胜率 53.6%（收益 = 海克斯胜率 − 英雄胜率）
    return {"patch": patch, "heroes": {"17": {
        "name": "迅捷斥候", "fetched_at": "2026-09-28 18:47",
        "augments": [
            {"augment_id": "2128", "win_rate": "0.600", "games": "90000", "win_rate_gain": "+6.4%"},
            {"augment_id": "1373", "win_rate": "0.540", "games": "80000", "win_rate_gain": "+0.4%"},
            {"augment_id": "1029", "win_rate": "0.520", "games": "70000", "win_rate_gain": "-1.6%"},
            {"augment_id": "2095", "win_rate": "0.700", "games": "30000", "win_rate_gain": "+16.4%"},
            {"augment_id": "1068", "win_rate": "0.536", "games": "60000", "win_rate_gain": "+<0.01%"},
        ],
        "items": [
            {"item_id": "3118", "win_rate": "0.52", "pick_rate": "0.30", "games": "300000", "item_fit": ""},
            {"item_id": "6653", "win_rate": "0.55", "pick_rate": "0.60", "games": "600000", "item_fit": "0.012"},
            {"item_id": "3089", "win_rate": "0.58", "pick_rate": "0.10", "games": "100000", "item_fit": ""},
            {"item_id": "3109", "win_rate": "0.71", "pick_rate": "0.0001", "games": "63", "item_fit": ""},
            {"item_id": "2530", "item_name": "歌之权冠/耳语头环", "win_rate": "0.50", "pick_rate": "0.05", "games": "50000", "item_fit": ""},
        ],
        "spells": [
            {"spell_combo": "闪现+标记", "win_rate": "0.534", "pick_rate": "0.304", "games": "300000"},
            {"spell_combo": "闪现+幽灵疾步", "win_rate": "0.539", "pick_rate": "0.589", "games": "600000"},
        ],
    }}}


def test_parse_hero_base_and_order():
    h = hexdata.parse(_snap())["17"]
    assert abs(h["sample_win"] - 0.536) < 1e-9  # 截断的 "+<0.01%" 不参与反推
    assert h["augments"]["2128"] == {"win": 0.6, "games": 90000}
    assert [x["id"] for x in h["items"]][:2] == ["6653", "3118"]  # 解析时按出场率排
    assert h["spells"][0]["names"] == ["闪现", "幽灵疾步"]


def test_hexdata_preferred_when_current(store):
    (store.root / "hexdata.json").write_text(json.dumps(_snap(), ensure_ascii=False), encoding="utf-8")
    p = hero_panel(store, "17")
    assert p["win_source"] == "Hexdata"
    a = next(x for x in p["augments"] if x["id"] == "2128")
    assert a["source"] == "hexdata" and a["games"] == 90000
    # 出装按胜率排，但样本太少的（63 场、胜率 71%）不参与
    assert [x["item"]["id"] for x in p["builds"]["first"]] == ["3089", "6653", "3118"]
    assert hexdata.parse(_snap())["17"]["items"][-2]["name"] == "歌之权冠"  # 腾讯装备表里没有的，用 Hexdata 的名字
    top = p["summoners"][0]
    assert [s["name"] for s in top["spells"]] == ["闪现", "幽灵疾步"]
    assert top["spells"][0]["id"] == "4" and top["spells"][0]["icon"]
    assert store.status()["hexdata_heroes"] == 1


def test_hexdata_stale_patch_falls_back(store):
    (store.root / "hexdata.json").write_text(json.dumps(_snap("16.18"), ensure_ascii=False), encoding="utf-8")
    assert store.hexdata_hero("17") is None
    p = hero_panel(store, "17")
    assert p["win_source"] == "ARAMGG" and p["summoners"] == []
    assert store.status()["hexdata_heroes"] == 0


def test_dice_is_not_best(store):
    (store.root / "hexdata.json").write_text(json.dumps(_snap(), ensure_ascii=False), encoding="utf-8")
    ev = evaluate(store, "17", ["2095", "2128", "1029"])
    assert ev["slots"][ev["best_index"]]["augment_id"] == "2128"
    dice = ev["slots"][0]
    assert dice["source"] == "hexdata" and dice["thin"] == "suspect"
    assert "数据存疑" in ev["advice"]


def test_builds_sorted_by_win_with_enough_sample():
    from lolhex.panel import by_win
    rows = [{"pick": 0.30, "win": 0.49}, {"pick": 0.01, "win": 0.60}, {"pick": 0.20, "win": 0.52}]
    assert [x["win"] for x in by_win(rows)] == [0.52, 0.49]  # 出场 1% 不到最热门的 1/10：不参与
