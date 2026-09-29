"""离线版：只读自带数据快照，从不联网；Hexdata 当前版本优先。"""

import pytest

from lolhex.config import Settings
from lolhex.data import offline, tencent
from lolhex.engine import Engine
from lolhex.panel import hero_panel


def _no_net(*a, **k):
    raise AssertionError("离线版不应联网")


@pytest.fixture
def no_network(monkeypatch):
    for name in dir(tencent):
        if name.startswith("fetch_"):
            monkeypatch.setattr(tencent, name, _no_net)
    from lolhex.data import aramgg, http, huya
    monkeypatch.setattr(http, "get_json", _no_net)
    monkeypatch.setattr(aramgg, "fetch_config", _no_net)
    monkeypatch.setattr(huya, "fetch", _no_net)


def test_bundled_data_complete():
    d = offline.bundled_dir()
    assert d is not None
    s = offline.OfflineStore(d)
    st = s.status()
    assert st["source"] == "offline" and st["hexdata_heroes"] == len(s.heroes) == 173
    assert len(list((d / "hero").glob("*.json"))) == 173


def test_offline_panel_without_network(no_network):
    s = offline.OfflineStore(offline.bundled_dir())
    s.refresh(force=True)
    p = hero_panel(s, "901")  # 小火龙
    assert p["win_source"] == "Hexdata" and p["builds"]["first"] and p["summoners"]
    assert p["rank"]["tier"]  # ARAMGG 层级来自缓存，不需要 Key


def test_engine_uses_bundled_data(tmp_path):
    e = Engine(Settings(), home=tmp_path)
    assert isinstance(e.store, offline.OfflineStore)
    e2 = Engine(Settings(offline=False, nas_url=""), home=tmp_path)
    assert not isinstance(e2.store, offline.OfflineStore)


def test_speed_factor():
    assert Settings().speed_factor == 1.0
    assert Settings(speed="low").speed_factor == 4.0
    assert Settings(speed="bogus").speed_factor == 1.0


def test_dashboard_hidden_without_service(tmp_path):
    assert Engine(Settings(), home=tmp_path).dashboard_url is None  # 离线版没有网页看板
    e = Engine(Settings(offline=False, nas_url="http://127.0.0.1:9"), home=tmp_path)
    assert e.dashboard_url == "http://127.0.0.1:9/"
