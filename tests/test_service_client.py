import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from conftest import fixture

from lolhex.engine import pick_my_hero


def test_pick_my_hero_by_largest_name():
    # 选人界面：自己的英雄名字号最大；队友列表的英雄名较小
    assert pick_my_hero([("17", 95, 60), ("157", 92, 22), ("1", 90, 22)]) == ("17", ["17", "157", "1"])
    # 字号差不多：不自动认定，只给候选
    mine, cands = pick_my_hero([("17", 95, 24), ("157", 92, 22)])
    assert mine is None and cands == ["17", "157"]
    assert pick_my_hero([]) == (None, [])
    assert pick_my_hero([("17", 90, 30), ("17", 99, 20)])[0] == "17"


def _serve(store, tmp_path):
    from lolhex.service.__main__ import Syncer, make_handler
    syncer = Syncer(store, tmp_path)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(store, syncer, 300))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.read()


def test_service_endpoints(store, tmp_path):
    httpd, base = _serve(store, tmp_path)
    try:
        assert json.loads(_get(base + "/health")[1])["ok"] is True
        status, html = _get(base + "/")
        assert status == 200 and "海克斯大乱斗数据" in html.decode("utf-8")
        heroes = json.loads(_get(base + "/api/heroes")[1])
        assert heroes[0]["rank"]["rank"] == 1          # 按腾讯排名排序
        panel = json.loads(_get(base + "/api/hero/Teemo/panel")[1])
        assert panel["hero"]["name"] == "提莫" and panel["rank"]["total"]
        assert panel["builds"]["core"] and panel["skills"][0]["max"] == ["Q", "E", "W"]
        payload = json.loads(_get(base + "/api/hero/17")[1])
        assert set(payload) == {"tencent", "aramgg", "hexdata", "huya"}
        b = json.loads(_get(base + "/api/bundle")[1])
        assert "heroes" not in b["huya"] and b["static"]["patch"] == "16.19"
        st = json.loads(_get(base + "/api/status")[1])
        assert "sync" in st and "data" in st
    finally:
        httpd.shutdown()


def test_remote_store_reads_from_nas(store, tmp_path, monkeypatch):
    from lolhex import recommend
    from lolhex.data.remote import RemoteStore
    httpd, base = _serve(store, tmp_path / "svc")
    try:
        rs = RemoteStore(tmp_path / "client", base)
        rs.refresh()
        assert rs.remote_ok is True and rs.status()["source"] == "nas"
        assert rs.resolve_hero("提莫") == "17"
        ev = recommend.evaluate(rs, "17", ["2128", "1029", "1373"])
        assert ev["best_index"] == 1           # 与直接用本地数据的结论一致
    finally:
        httpd.shutdown()


def test_remote_store_falls_back_when_nas_down(tmp_path, monkeypatch):
    from lolhex.data.remote import RemoteStore
    called = {}

    def fake_refresh(self, force=False):
        called["direct"] = True

    monkeypatch.setattr("lolhex.data.store.DataStore.refresh", fake_refresh)
    rs = RemoteStore(tmp_path, "http://127.0.0.1:9")  # 不可达
    rs.refresh()
    assert rs.remote_ok is False and called.get("direct") and rs.status()["source"] == "direct"


def test_engine_has_no_lcu(store, tmp_path):
    import lolhex.engine as eng_mod
    from lolhex.config import Settings
    src = open(eng_mod.__file__, encoding="utf-8").read()
    assert "lcu" not in src.lower().replace("不接入 lcu", "")
    e = eng_mod.Engine(Settings(nas_url="", use_liveclient=False), home=tmp_path, store=store)
    assert e.live is None
    e.set_hero("Teemo")
    s = e.snapshot()
    assert s["hero_id"] == "17" and s["hero_source"] == "manual"
    with e._lock:
        e.state["offer"] = {"slots": ["2128", None, "1373"], "texts": [], "scores": [], "boxes": [], "at": 0}
    e.correct_slot(1, "1029")
    assert e.snapshot()["evaluation"]["best_index"] == 1
    assert e.hero_panel("17")["hero"]["name"] == "提莫"


def test_cards_show_before_marker(store, tmp_path, monkeypatch):
    """开局选卡时没有"可用"两个字，卡片也要标注，不能等点完卡才出来。"""
    import lolhex.engine as eng_mod
    from lolhex.config import Settings
    from lolhex.vision import champselect
    from lolhex.vision.ocr import OCR
    monkeypatch.setattr(OCR, "get", classmethod(lambda cls: type("O", (), {"recognize": None, "detect": None})()))
    monkeypatch.setattr(champselect, "is_champ_select", lambda *a, **k: False)
    card = {"slot": 0, "hero_id": "17", "score": 0.99, "box": (0, 0, 10, 10)}
    monkeypatch.setattr(champselect, "read_cards", lambda *a, **k: [card])
    e = eng_mod.Engine(Settings(nas_url="", use_liveclient=False), home=tmp_path, store=store)
    cs = e.analyze_champ_select(None)
    assert [c["hero_id"] for c in cs["cards"]] == ["17"] and cs["team"] == []
    monkeypatch.setattr(champselect, "read_cards", lambda *a, **k: [])
    assert e.analyze_champ_select(None) is False  # 既没"可用"也没卡：不在选人界面






def test_dashboard_script_is_valid_javascript(tmp_path):
    """看板页面脚本一旦有语法错误，整页都不会有数据；有 node 时用它做语法检查。"""
    import pathlib
    import re
    import shutil
    import subprocess
    import pytest
    node = shutil.which("node")
    if not node:
        pytest.skip("没有 node")
    root = pathlib.Path(__file__).resolve().parent.parent
    html = (root / "lolhex/service/dashboard.html").read_text(encoding="utf-8")
    js = tmp_path / "dash.js"
    js.write_text("\n".join(re.findall(r"<script>(.*?)</script>", html, re.S)), encoding="utf-8")
    r = subprocess.run([node, "--check", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_aramgg_backfill_stops_at_reserve_and_resumes(store, tmp_path, monkeypatch):
    """额度不够时停在半路，下一轮/第二天接着补。"""
    from lolhex.data import aramgg
    from lolhex.service import __main__ as svc
    left = {"n": 26}
    calls = []

    def fake_fetch(hid, key):
        calls.append(hid)
        left["n"] -= 2
        return {"hid": hid}, left["n"]

    monkeypatch.setattr(aramgg, "fetch_champion_augments", fake_fetch)
    monkeypatch.setattr(aramgg, "fetch_champions_stats", lambda key: ([], None))
    monkeypatch.setattr(aramgg, "parse_champion_augments", lambda raw, patch=None: {"augments": {}})
    cfg = {"dataVersion": "v1", "gamePatch": "16.18", "publishedAt": "2026-09-21T09:31:09Z"}
    monkeypatch.setattr(aramgg, "fetch_config", lambda: dict(cfg))
    monkeypatch.setattr(svc, "HERO_PAUSE_S", 0)
    store.aramgg_key = "k"
    syncer = svc.Syncer(store, tmp_path)
    syncer.aramgg_pass()
    assert len(calls) == 4 and store.aramgg_low()  # 26→18，低于保留 20 就停
    store._aramgg_config["remaining_day"] = "1999-01-01"  # 第二天额度恢复
    left["n"] = 400
    syncer.aramgg_pass()
    assert all(store.aramgg_fresh(h) for h in store.heroes)
    assert syncer.state["aramgg_progress"] == f"{len(store.heroes)}/{len(store.heroes)}"
    n = len(calls)
    syncer.aramgg_pass()
    assert len(calls) == n  # 都是当前版本，不再花额度
    # ARAMGG 重新发布（版本号不变、发布时间变了）：一小时内发现，全部按热度重抓
    cfg["publishedAt"] = "2026-09-27T09:00:00Z"
    store._aramgg_config["checked_at"] = 0
    syncer.aramgg_pass()
    assert len(calls) == n + len(store.heroes)


def test_aramgg_429_retries_hourly(store, monkeypatch):
    """额度被拒（429）后不锁一整天：一小时后再试，成功就接着抓。"""
    import time as _time
    from lolhex.data import aramgg
    state = {"quota": False}

    def fake_fetch(hid, key):
        if not state["quota"]:
            raise aramgg.QuotaExhausted("ARAMGG 今日额度已用完")
        return {"hid": hid}, 190

    monkeypatch.setattr(aramgg, "fetch_champion_augments", fake_fetch)
    monkeypatch.setattr(aramgg, "fetch_champions_stats", lambda key: ([], None))
    monkeypatch.setattr(aramgg, "parse_champion_augments", lambda raw, patch=None: {"augments": {}})
    monkeypatch.setattr(aramgg, "fetch_config", lambda: {"dataVersion": "v1", "publishedAt": "p"})
    store.aramgg_key = "k"
    hid = next(iter(store.heroes))
    assert store.aramgg_hero(hid) is None
    assert store.aramgg_low() and store.last_error is None  # 被拒不算报错
    store._aramgg_config["exhausted_at"] = _time.time() - 3700  # 过了一小时
    assert not store.aramgg_low()
    state["quota"] = True
    assert store.aramgg_hero(hid) and not store.aramgg_low()
    assert "exhausted_at" not in store._aramgg_config


def test_aramgg_auto_fetches_on_release_only(store, tmp_path, monkeypatch):
    """默认自动：ARAMGG 有新发布才抓，200 点一天抓完全部英雄；查英雄、看板从不实时抓。"""
    from lolhex.data import aramgg
    from lolhex.service import __main__ as svc
    left = {"n": 200}
    calls = []

    def fake_fetch(hid, key):
        calls.append(hid)
        left["n"] -= 1
        return {"hid": hid}, left["n"]

    def fake_stats(key):
        left["n"] -= 1
        return [], left["n"]

    monkeypatch.setattr(aramgg, "fetch_champion_augments", fake_fetch)
    monkeypatch.setattr(aramgg, "fetch_champions_stats", fake_stats)
    monkeypatch.setattr(aramgg, "parse_champion_augments", lambda raw, patch=None: {"augments": {}})
    monkeypatch.setattr(aramgg, "fetch_config", lambda: {"dataVersion": "v1", "publishedAt": "p"})
    monkeypatch.setattr(svc, "HERO_PAUSE_S", 0)
    store.aramgg_key = "k"
    store.aramgg_auto = False  # 和 main() 一样：服务里的 store 从不实时抓
    httpd, base = _serve(store, tmp_path)
    try:
        _get(base + "/api/hero/17")
        _get(base + "/api/hero/17/panel")
        assert calls == []  # 游戏机查英雄不花额度
    finally:
        httpd.shutdown()
    syncer = svc.Syncer(store, tmp_path)
    syncer.aramgg_auto = True
    syncer.aramgg_pass()
    assert len(calls) == len(store.heroes) and all(store.aramgg_fresh(h) for h in store.heroes)
    n = len(calls)
    syncer.aramgg_pass()
    assert len(calls) == n  # 没有新发布：不再请求


def test_aramgg_manual_only(store, tmp_path, monkeypatch):
    """关掉自动抓取后：看板、查英雄都不花额度；只有 POST /api/aramgg/fetch?limit=N 才抓，最多 N 个。"""
    from lolhex.data import aramgg
    from lolhex.service import __main__ as svc
    calls = []

    def fake_fetch(hid, key):
        calls.append(hid)
        return {"hid": hid}, 100

    monkeypatch.setattr(aramgg, "fetch_champion_augments", fake_fetch)
    monkeypatch.setattr(aramgg, "fetch_champions_stats", lambda key: ([], None))
    monkeypatch.setattr(aramgg, "parse_champion_augments", lambda raw, patch=None: {"augments": {}})
    monkeypatch.setattr(aramgg, "fetch_config", lambda: {"dataVersion": "v1", "publishedAt": "p"})
    monkeypatch.setattr(svc, "HERO_PAUSE_S", 0)
    store.aramgg_key = "k"
    store.aramgg_auto = False
    httpd, base = _serve(store, tmp_path)
    try:
        _get(base + "/api/hero/17")
        _get(base + "/api/hero/17/panel")
        assert calls == []
        req = urllib.request.Request(base + "/api/aramgg/fetch", method="POST", data=b"")
        try:
            urllib.request.urlopen(req, timeout=5)
            raise AssertionError("没给 limit 应该拒绝")
        except urllib.error.HTTPError as e:
            assert e.code == 400
        req = urllib.request.Request(base + "/api/aramgg/fetch?limit=2", method="POST", data=b"")
        assert urllib.request.urlopen(req, timeout=5).status == 202
        for _ in range(50):
            if json.loads(_get(base + "/api/status")[1])["sync"].get("aramgg_progress", "").startswith("2/"):
                break
            threading.Event().wait(0.05)
        assert len(calls) == 2
        assert json.loads(_get(base + "/api/status")[1])["sync"]["aramgg_auto"] is False
    finally:
        httpd.shutdown()




def _probe_setup(store, tmp_path, monkeypatch, new_sample):
    """所有英雄都有旧发布 v0 的数据（胜率日期 09-21、样本 100 场）；ARAMGG 发布了 v1。"""
    from lolhex.data import aramgg
    from lolhex.service import __main__ as svc
    calls = []

    def fake_fetch(hid, key):
        calls.append(hid)
        return {"hid": hid}, 150

    monkeypatch.setattr(aramgg, "fetch_champion_augments", fake_fetch)
    monkeypatch.setattr(aramgg, "fetch_champions_stats", lambda key: ([], 150))
    monkeypatch.setattr(aramgg, "parse_champion_augments",
                        lambda raw, patch=None: {"augments": {}, "win_date": "2026-09-21", "sample_games": new_sample})
    monkeypatch.setattr(aramgg, "fetch_config", lambda: {"dataVersion": "v1", "publishedAt": "p1", "gamePatch": "16.19"})
    monkeypatch.setattr(svc, "HERO_PAUSE_S", 0)
    store.aramgg_key = "k"
    (store.root / "aramgg").mkdir(parents=True, exist_ok=True)
    for h in store.heroes:
        (store.root / "aramgg" / f"{h}.json").write_text(json.dumps(
            {"augments": {}, "win_date": "2026-09-21", "sample_games": 100, "release": "v0@p0", "patch": "16.18"}),
            encoding="utf-8")
    syncer = svc.Syncer(store, tmp_path)
    syncer.aramgg_auto = True
    return syncer, calls


def test_aramgg_new_release_same_wins_adopts(store, tmp_path, monkeypatch):
    """新发布但胜率没更新（抽查的英雄胜率日期、样本都没变）：只花 1 点，其余英雄沿用旧数据。"""
    syncer, calls = _probe_setup(store, tmp_path, monkeypatch, new_sample=100)
    syncer.aramgg_pass()
    assert len(calls) == 1
    assert all(store.aramgg_fresh(h) for h in store.heroes)
    other = next(h for h in store.heroes if h != calls[0])
    assert store.aramgg_cached(other)["adopted_from"] == "v0@p0"
    assert store.aramgg_cached(other)["patch"] == "16.19"


def test_aramgg_new_release_new_wins_fetches_all(store, tmp_path, monkeypatch):
    """抽查发现样本变了：照常全部重抓。"""
    syncer, calls = _probe_setup(store, tmp_path, monkeypatch, new_sample=120)
    syncer.aramgg_pass()
    assert len(calls) == len(store.heroes)


def test_aramgg_pass_stops_on_network_error(store, tmp_path, monkeypatch):
    """请求失败（网络问题）：这一轮只试一次就停，不对每个英雄都失败一次。"""
    from lolhex.data import aramgg
    from lolhex.service import __main__ as svc
    calls = []

    def boom(hid, key):
        calls.append(hid)
        raise ConnectionError("refused")

    monkeypatch.setattr(aramgg, "fetch_champion_augments", boom)
    monkeypatch.setattr(aramgg, "fetch_champions_stats", lambda key: ([], 150))
    monkeypatch.setattr(aramgg, "fetch_config", lambda: {"dataVersion": "v1", "publishedAt": "p"})
    monkeypatch.setattr(svc, "HERO_PAUSE_S", 0)
    store.aramgg_key = "k"
    syncer = svc.Syncer(store, tmp_path)
    syncer.aramgg_pass()
    assert len(calls) == 1
