from lolhex import recommend


def test_smoothing_pulls_small_samples_to_baseline():
    big = recommend.smoothed_delta(0.60, 20000, 0.50, 300)
    small = recommend.smoothed_delta(0.80, 20, 0.50, 300)
    assert 9.5 < big < 10
    assert small < 2.0  # 20 局 80% 胜率不应压过 2 万局 60%
    assert recommend.smoothed_delta(None, 100, 0.5, 300) is None


def test_win_rate_beats_pick_based_tier(store):
    # 腾讯把炽燃利息排黄金第 1（按层级/选取），但提莫带虚幻武器的胜率明显更高。
    ev = recommend.evaluate(store, "17", ["2128", "1029", "1373"])
    names = [s["name"] for s in ev["slots"]]
    assert names == ["炽燃利息", "虚幻武器", "缩小引擎"]
    assert ev["best_index"] == 1
    assert ev["slots"][1]["verdict"] == "best" and ev["slots"][1]["basis"] == "hero_win"
    assert ev["slots"][0]["tier"] == "S" and ev["slots"][0]["rank"] == 1
    assert ev["slots"][1]["sample"] == "high"
    assert "首选「虚幻武器」" in ev["advice"]


def test_unknown_slot_and_rare_augment(store):
    ev = recommend.evaluate(store, "17", ["1029", None, "1001"])
    assert ev["slots"][1]["verdict"] == "unknown" and ev["slots"][1]["score"] is None
    assert ev["slots"][2]["basis"] == "rare" and ev["slots"][2]["verdict"] == "reroll"
    assert ev["best_index"] == 0


def test_without_hero_uses_global_win_rate(store):
    ev = recommend.evaluate(store, None, ["2128", "1029", "1001"])
    assert all(s["basis"] == "global_win" for s in ev["slots"])
    assert "未识别英雄" in ev["advice"]


def test_all_below_baseline_suggests_reroll(store, monkeypatch):
    hy = store.huya["heroes"]["17"]["augments"]
    for aid in ("2128", "1029", "1373"):
        hy[aid] = {"win": 0.45, "games": 50000, "pick": 0.1, "tier": "T3"}
    ev = recommend.evaluate(store, "17", ["2128", "1029", "1373"])
    assert all(s["verdict"] in ("best", "reroll") for s in ev["slots"])
    assert ev["advice"].startswith("三张都低于英雄基准")


def test_sample_levels():
    assert recommend.sample_level(None) == "none"
    assert recommend.sample_level(100) == "low"
    assert recommend.sample_level(500) == "medium"
    assert recommend.sample_level(5000) == "high"


def test_mayhem_dictionary_excludes_arena_only(store):
    store.static["augments"]["99999"] = {"id": "99999", "name": "仅竞技场", "rarity": "gold", "modes": ["CHERRY"]}
    assert "99999" not in store.mayhem_augments()
    assert "1029" in store.mayhem_augments()


def test_resolve_hero_variants(store):
    for key in ("17", "Teemo", "提莫", "迅捷斥候", "game_character_displayname_Teemo", 17):
        assert store.resolve_hero(key) == "17"
    assert store.resolve_hero("不存在") is None


def test_patch_drift_correct_distrust_and_new(store):
    # 虎牙快照 16.17、当前 16.19：按总体胜率变化决定修正 / 弃用旧胜率
    g = store.ranks["augments"]
    g.setdefault("1373", {})["win"] = 0.55
    g.setdefault("1029", {})["win"] = 0.50
    g.setdefault("2128", {})["win"] = 0.53
    store.huya["augment_global"] = {"1373": 0.535, "1029": 0.56, "2128": 0.53}  # 2128 无变化
    assert store.augment_drift() == {"1373": 1.5, "1029": -6.0, "2128": 0.0}

    ev = recommend.evaluate(store, "17", ["2128", "1029", "1373"])
    burn, weapon, shrink = ev["slots"]
    assert burn["basis"] == "hero_win" and "drift" not in burn
    assert weapon["basis"] == "tier_only" and weapon["drift"] == -6.0   # 大改：不用旧胜率
    assert any("版本改动大" in x for x in weapon["reasons"])
    base = recommend.evaluate(store, "17", ["1373", None, None])["slots"][0]
    assert shrink["basis"] == "hero_win" and shrink["drift"] == 1.5
    assert abs(shrink["score"] - base["score"]) < 1e-9  # 同一次计算里已含修正
    assert any("已修正" in x for x in shrink["reasons"])

    # 虎牙快照里没有的新海克斯
    store.huya["augment_global"].pop("2128")
    ev = recommend.evaluate(store, "17", ["2128", None, None])
    assert ev["slots"][0]["basis"] == "tier_only"
    assert any("新海克斯" in x for x in ev["slots"][0]["reasons"])


def test_no_drift_when_same_patch(store):
    store.huya["patch"] = store.static["patch"]
    store.huya["augment_global"] = {"1029": 0.30}
    ev = recommend.evaluate(store, "17", ["1029", None, None])
    assert ev["slots"][0]["basis"] == "hero_win" and "drift" not in ev["slots"][0]


def _with_aramgg(store):
    import json
    from conftest import fixture
    from lolhex.data import aramgg
    parsed = aramgg.parse_champion(fixture("aramgg_champion17.json"))
    parsed["release"] = parsed["data_version"] + "@"
    (store.root / "aramgg").mkdir(exist_ok=True)
    (store.root / "aramgg" / "17.json").write_text(json.dumps(parsed, ensure_ascii=False), encoding="utf-8")
    store.aramgg_key = "test"
    store._aramgg_config = {"data_version": parsed["data_version"], "checked_at": 9e12}
    return parsed


def test_aramgg_parse():
    from conftest import fixture
    from lolhex.data import aramgg
    p = aramgg.parse_champion(fixture("aramgg_champion17.json"))
    assert p["patch"] == "16.18" and p["data_version"] == "16.18.3"
    a = p["augments"]["1029"]
    assert 0.6 < a["win"] < 0.63 and a["games"] > 50000 and a["region"] == "WORLD"
    assert 0.52 < p["sample_win"] < 0.55   # 与腾讯官方 16.18 提莫胜率 53.49% 接近


def test_aramgg_is_primary_and_cross_checked(store):
    _with_aramgg(store)
    ev = recommend.evaluate(store, "17", ["2128", "1029", "1373"])
    assert all(s["source"] == "aramgg" for s in ev["slots"])
    assert ev["best_index"] == 1
    assert any("ARAMGG 16.18" in x for x in ev["slots"][1]["reasons"])
    assert ev["sources"]["aramgg_patch"] == "16.18"


def test_aramgg_missing_falls_back_to_huya(store):
    parsed = _with_aramgg(store)
    parsed["augments"]["1029"]["win"] = None  # 不足 255 局时 ARAMGG 不给胜率
    store._aramgg["17"] = parsed
    ev = recommend.evaluate(store, "17", ["1029", None, None])
    assert ev["slots"][0]["source"] == "huya"


def test_no_key_means_no_aramgg(store):
    assert store.aramgg_hero("17") is None


def test_thin_sample_is_never_first_choice(store):
    """冷门海克斯局数少、胜率略高：不当首选；少一个数量级以上提示刷新（黑默丁格 夜狩 vs 魔法飞弹）。"""
    parsed = _with_aramgg(store)
    augs = parsed["augments"]
    base = parsed["sample_win"]
    augs["1029"].update(win=base - 0.006, games=14281)   # 热门、样本足
    augs["2128"].update(win=base + 0.03, games=385)      # 冷门、胜率高，少两个数量级
    store._aramgg["17"] = parsed
    ev = recommend.evaluate(store, "17", ["1029", "2128", None])
    assert ev["best_index"] == 0
    thin = ev["slots"][1]
    assert thin["score"] > ev["slots"][0]["score"]
    assert thin["thin"] == "too_few" and thin["verdict"] == "reroll"
    assert "样本太少" in ev["advice"]
    augs["1029"]["games"] = 1200   # 只是不足 1000 局：不当首选，但不提示刷新
    augs["2128"]["games"] = 900
    ev = recommend.evaluate(store, "17", ["1029", "2128", None])
    assert ev["best_index"] == 0 and ev["slots"][1]["thin"] == "few" and ev["slots"][1]["verdict"] == "ok"
    augs["1029"]["games"] = 300    # 都不足时正常比较
    augs["2128"]["games"] = 385
    ev = recommend.evaluate(store, "17", ["1029", "2128", None])
    assert ev["best_index"] == 1


def test_aramgg_1credit_matches_2credit():
    """1 credit 的 /data/champion-augments 与 2 credits 的 /champions 海克斯数据逐项一致（提莫实测）。"""
    from conftest import fixture
    from lolhex.data import aramgg
    rich = aramgg.parse_champion(fixture("aramgg_champion17.json"))
    raw = aramgg.parse_champion_augments(fixture("aramgg_champion_augments17.json"))
    assert raw["patch"] == "16.18" and set(raw["augments"]) == set(rich["augments"])
    for aid, a in rich["augments"].items():
        b = raw["augments"][aid]
        for k in ("win", "wins", "games", "tier", "rank", "total", "region"):
            assert a[k] == b[k], (aid, k, a[k], b[k])
        assert abs(a["pick"] - b["pick"]) < 1e-9
    assert abs(raw["sample_win"] - rich["sample_win"]) < 1e-12
    tiers = aramgg.parse_champions_stats(fixture("aramgg_champions_stats.json"))
    assert tiers["17"]["tier"] == rich["champion_tier"] == 1
