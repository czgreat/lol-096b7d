"""测试夹具：用 2026-09-25 实抓并裁剪过的真实数据，离线构建 DataStore。"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIX = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))


def fixture(name: str):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _no_paid_aramgg(monkeypatch):
    """测试绝不能真的请求 ARAMGG（会用掉额度）：没替换的付费接口一调用就报错。"""
    from lolhex.data import aramgg

    def boom(url, key):
        raise AssertionError(f"测试里请求了真实的 ARAMGG 付费接口：{url}")
    monkeypatch.setattr(aramgg, "_get_paid", boom)


@pytest.fixture
def store(tmp_path, monkeypatch):
    """离线 DataStore：静态资料、榜单、虎牙数据、提莫的单英雄数据都已就绪，且禁止联网。"""
    from lolhex.data import huya, tencent
    from lolhex.data.store import DataStore

    def no_network(*a, **k):
        raise AssertionError("测试中不应联网")

    monkeypatch.setattr("lolhex.data.http.get", no_network)
    monkeypatch.setattr("lolhex.data.http.head_ok", no_network)

    now = time.time()
    root = tmp_path / "data"
    root.mkdir()
    static = {
        "fetched_at": now, "patch": "16.19", "versions": [{"name": "16.19"}],
        "heroes": tencent.parse_hero_list(fixture("tencent_hero_list.json")),
        "augments": tencent.parse_kiwi_augments(fixture("tencent_kiwi_augments.json")),
        "items": tencent.parse_items(fixture("tencent_items.json")),
        "spells": tencent.parse_summoner_spells(fixture("tencent_summoner_spells.json")),
    }
    hdate, heroes = tencent.parse_hero_rank(fixture("tencent_hero_rank.json"))
    adate, augs = tencent.parse_augment_rank(fixture("tencent_augment_rank.json"))
    ranks = {"fetched_at": now, "date": adate, "heroes": heroes, "augments": augs}
    hy = huya.parse_champion_detail(fixture("huya_champion_detail.json"))
    hy.update(version=395, fetched_at=now)
    hero17 = tencent.parse_hero_hex(fixture("tencent_hero17.json"))
    hero17.update(spells=tencent.parse_hero_spells(fixture("tencent_hero17_spells.json")),
                  fetched_at=now, patch="16.19")
    for name, blob in (("static.json", static), ("ranks.json", ranks), ("huya.json", hy)):
        (root / name).write_text(json.dumps(blob, ensure_ascii=False), encoding="utf-8")
    (root / "hero").mkdir()
    (root / "hero" / "17.json").write_text(json.dumps(hero17, ensure_ascii=False), encoding="utf-8")
    return DataStore(root)
