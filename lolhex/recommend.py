"""三选一评分：以胜率为主，层级只做兜底。

数据现实（2026-09 实测，详见 docs/data-sources.md）：
- 腾讯单英雄海克斯数据只有「层级 S/A/B/C + 选取率」，没有胜率；腾讯海克斯总榜有全英雄胜率。
- 单英雄胜率来源依次为：Hexdata 快照（国服，样本约 ARAMGG 的 7 倍，只用当前版本的）
  → ARAMGG（客户端上传，约 97% 国服，比当前版本最多晚一版）→ 虎牙国服快照（停在 16.17，按总体胜率变化修正/弃用）→ 腾讯层级 → 腾讯总体胜率。

分数 = 相对该英雄基准胜率的Δ胜率（百分点），计算方式：
1. 贝叶斯平滑：smoothed = (胜率×场次 + 基准×k) / (场次 + k)，k 默认 300，
   小样本的高胜率会被拉回基准附近（与 Hexdata 的 Wilson 下界同样目的）。
2. Δ = smoothed − 该英雄基准胜率。
3. 样本分档：<250 局仅参考、250–999 中等、≥1000 充足，显示在界面上。
4. 首选只在样本充足（≥1000 局）的海克斯里挑：冷门海克斯偶尔胜率高，多半是局数少碰巧打出来的。
   比同屏其他海克斯少一个数量级以上（<1/10）的，标"样本太少"并提示刷新，不管胜率多高；
   只是不足 1000 局的，不当首选、标"样本偏少"。三张都不足时才正常比较。
没有胜率时才用腾讯层级粗估（S +1.5 / A +0.5 / B −0.5 / C −1.5），并标为"仅层级"。
选取率只展示，不进分数：常拿不代表强。
"""

from __future__ import annotations

from .data.store import DataStore
from .data.tencent import RARITY_CN

TIER_PP = {"S": 1.5, "A": 0.5, "B": -0.5, "C": -1.5, "D": -2.5,
           "T0": 2.0, "T1": 1.5, "T2": 0.5, "T3": -0.5, "T4": -1.5, "T5": -2.5}
DRIFT_CORRECT = 1.0   # 虎牙快照落后时：总体胜率变化 ≥1pp 的海克斯，按变化量修正单英雄Δ
DRIFT_DISTRUST = 3.0  # 变化 ≥3pp（重做/大改）：不再使用旧的单英雄胜率
CROSS_CHECK_GAP = 2.0  # ARAMGG 与虎牙国服快照相差 ≥2pp 时提示
REROLL_BELOW = -0.5  # 低于英雄基准 0.5pp 以上：可考虑刷新
REROLL_GAP = 2.0     # 比首选低 2pp 以上：可考虑刷新
# 两家数据源对不上的海克斯：不当首选。掷骰狂人：64 个英雄 Hexdata 全部比 ARAMGG 低 1–8pp（口径不同）
SUSPECT = {"2095": "Hexdata 与 ARAMGG 这个海克斯的胜率差 1–8pp（统计口径不同），不作首选"}
RELIABLE_GAMES = 1000  # 本英雄局数达到这个数才能当首选
TOO_FEW_RATIO = 0.1    # 局数不到同屏最多那张的 1/10：样本太少，提示刷新


def sample_level(games: int | None) -> str:
    if not games:
        return "none"
    if games < 250:
        return "low"
    if games < 1000:
        return "medium"
    return "high"


SAMPLE_CN = {"none": "无样本", "low": "样本少，仅参考", "medium": "样本中等", "high": "样本充足"}


def smoothed_delta(win: float | None, games: int | None, base: float | None, k: int) -> float | None:
    """贝叶斯平滑后的Δ胜率（百分点）。"""
    if win is None or base is None or not games:
        return None
    s = (win * games + base * k) / (games + k)
    return (s - base) * 100


def evaluate(store: DataStore, hero_id: str | None, slots: list[str | None], k: int = 300) -> dict:
    hero = store.hero(hero_id) if hero_id else None
    hy = store.huya_hero(hero_id) if hero_id else None
    ag = store.win_data(hero_id) if hero_id else None  # 当前版本 Hexdata 优先，没有就 ARAMGG
    ag_name = "Hexdata" if (ag or {}).get("source") == "hexdata" else "ARAMGG"
    ag_augs = (ag or {}).get("augments") or {}
    ag_base = (ag or {}).get("sample_win")
    ag_patch = (ag or {}).get("patch")
    tencent_by_id = {a["id"]: a for a in (hero or {}).get("augments", [])}
    rarity_total: dict[str, int] = {}
    for a in tencent_by_id.values():
        if a.get("rarity"):
            rarity_total[a["rarity"]] = rarity_total.get(a["rarity"], 0) + 1
    base = (hy or {}).get("win")
    if base is None and hero_id:
        base = ((store.ranks.get("heroes") or {}).get(str(hero_id)) or {}).get("win")
    global_augs = store.ranks.get("augments") or {}
    wins = [g["win"] for g in global_augs.values() if g.get("win")]
    global_mean = sum(wins) / len(wins) if wins else None
    huya_patch = store.huya.get("patch")
    lag = bool(huya_patch) and huya_patch != store.static.get("patch")
    drift = store.augment_drift() if lag else {}
    huya_global = store.huya.get("augment_global") or {}

    results = []
    for idx, aid in enumerate(slots):
        r: dict = {"index": idx, "augment_id": aid, "score": None, "basis": None,
                   "verdict": "unknown", "reasons": []}
        if not aid:
            r["reasons"].append("未识别")
            results.append(r)
            continue
        meta = store.augments.get(aid, {})
        r.update(name=meta.get("name", aid), rarity=meta.get("rarity"), icon=meta.get("icon"),
                 desc=meta.get("desc", ""))
        t = tencent_by_id.get(aid)
        h = ((hy or {}).get("augments") or {}).get(aid)
        if t:
            rarity = t.get("rarity") or meta.get("rarity")
            r.update(tier=t.get("tier"), rank=t.get("rank"), rank_total=rarity_total.get(rarity),
                     pick=t.get("pick"))
            if t.get("rank"):
                r["reasons"].append(f"腾讯{RARITY_CN.get(rarity, '')}第{t['rank']}/"
                                    f"{rarity_total.get(rarity, '?')}（{t.get('tier') or '-'}级）")

        # 虎牙快照落后于当前版本时，看这个海克斯的总体胜率变了多少。
        dr = drift.get(aid)
        new_aug = lag and bool(huya_global) and aid not in huya_global
        distrust = new_aug or (dr is not None and abs(dr) >= DRIFT_DISTRUST)
        if dr is not None and abs(dr) >= DRIFT_CORRECT:
            r["drift"] = dr

        # 0) 本英雄胜率（ARAMGG，当前或上一版本；约 97% 国服样本）
        a = ag_augs.get(aid)
        if a and a.get("win") is not None and a.get("games") and ag_base is not None:
            d = smoothed_delta(a["win"], a["games"], ag_base, k)
            r.update(win=a["win"], games=a["games"], sample=sample_level(a["games"]),
                     source=(ag or {}).get("source") or "aramgg")
            r["reasons"].append(f"本英雄胜率 {a['win'] * 100:.1f}%（{a['games']}局，{SAMPLE_CN[r['sample']]}，"
                                f"{ag_name} {ag_patch}），平滑后较英雄基准 {d:+.1f}pp")
            if ag_patch and ag_patch != store.static.get("patch") and dr is not None and abs(dr) >= DRIFT_DISTRUST:
                r["reasons"].append(f"{huya_patch} 以来总体胜率变化 {dr:+.1f}pp，本版可能已不同")
            # 与虎牙国服快照交叉核对
            if h and h.get("games") and h.get("win") is not None and not distrust:
                hd = smoothed_delta(h["win"], h["games"], base, k)
                if hd is not None and abs(hd - d) >= CROSS_CHECK_GAP:
                    r["reasons"].append(f"国服快照（{huya_patch}）为 {hd:+.1f}pp，两者差异较大")
            r["score"] = round(d, 2)
            r["basis"] = "hero_win"
        # 1) 本英雄胜率（虎牙国服快照）
        elif h and h.get("games") and h.get("win") is not None and not distrust:
            r["source"] = "huya"
            d = smoothed_delta(h["win"], h["games"], base, k)
            r.update(win=h["win"], games=h["games"], sample=sample_level(h["games"]))
            if d is not None:
                note = f"{huya_patch}数据" if lag else ""
                r["reasons"].append(f"本英雄胜率 {h['win'] * 100:.1f}%（{h['games']}局，"
                                    f"{SAMPLE_CN[r['sample']]}{'，' + note if note else ''}），"
                                    f"平滑后较英雄基准 {d:+.1f}pp")
                if r.get("drift") is not None:
                    d += r["drift"]
                    r["reasons"].append(f"版本改动：总体胜率 {r['drift']:+.1f}pp，已修正")
                r["score"] = round(d, 2)
                r["basis"] = "hero_win"
        elif distrust and r["score"] is None:
            r["reasons"].append("新海克斯，旧数据里没有" if new_aug else
                                f"版本改动大（总体胜率 {dr:+.1f}pp），旧的本英雄胜率不再使用")
        # 2) 版本改动大且有当前层级：按层级
        if r["score"] is None and distrust and r.get("tier") in TIER_PP:  # 没有 ARAMGG 胜率且虎牙数据过期
            r["score"] = TIER_PP[r["tier"]]
            r["basis"] = "tier_only"
            r["reasons"].append("按腾讯当前层级估计，可信度低")
        # 3) 未识别英雄，或版本改动大又没有层级：全英雄胜率（腾讯总榜，当前版本）
        if r["score"] is None and (not hero_id or distrust):
            g = global_augs.get(aid)
            if g and g.get("win") and global_mean:
                d = (g["win"] - global_mean) * 100
                r.update(win=g["win"], score=round(d, 2), basis="global_win")
                r["reasons"].append(f"全英雄胜率 {g['win'] * 100:.1f}%，较平均 {d:+.1f}pp")
        # 3) 只有层级
        if r["score"] is None and r.get("tier") in TIER_PP:
            r["score"] = TIER_PP[r["tier"]]
            r["basis"] = "tier_only"
            r["reasons"].append("仅层级，无胜率数据，可信度低")
        if r["score"] is None:
            if hero_id and (tencent_by_id or hy):
                r["score"] = -3.0
                r["basis"] = "rare"
                r["reasons"].append("该英雄几乎不选，数据不足")
            else:
                r["reasons"].append("暂无可靠数据")
        results.append(r)

    scored = [r for r in results if r["score"] is not None]

    hero_games = [r.get("games") or 0 for r in scored if r.get("basis") == "hero_win"]
    most = max(hero_games, default=0)
    for r in scored:
        if r.get("basis") != "hero_win":
            continue
        g = r.get("games") or 0
        if r["augment_id"] in SUSPECT:
            r["thin"] = "suspect"
            r["reasons"].append(SUSPECT[r["augment_id"]])
        elif most >= RELIABLE_GAMES and g < most * TOO_FEW_RATIO:
            r["thin"] = "too_few"
            r["reasons"].append(f"只有 {g} 局，比同屏其他海克斯少一个数量级以上，胜率不可信")
        elif most >= RELIABLE_GAMES and g < RELIABLE_GAMES:
            r["thin"] = "few"
            r["reasons"].append(f"只有 {g} 局，胜率偶然性大，不作首选")

    pool = [r for r in scored if not r.get("thin")] or scored
    best = max(pool, key=lambda r: r["score"]) if pool else None
    passed = [r for r in scored if r is not best and r.get("thin") and best is not None and r["score"] > best["score"]]
    for r in scored:
        if r is best:
            r["verdict"] = "best"
        elif r.get("thin") == "too_few":
            r["verdict"] = "reroll"
        elif r.get("thin"):
            r["verdict"] = "ok"
        elif r["score"] < REROLL_BELOW or r["score"] <= best["score"] - REROLL_GAP:
            r["verdict"] = "reroll"
        else:
            r["verdict"] = "ok"

    if best is None:
        advice = "暂无可靠数据，请自行判断"
    elif len(scored) == len(slots) and all(r["score"] < REROLL_BELOW for r in scored):
        advice = f"三张都低于英雄基准，可考虑刷新；非要选就拿「{best.get('name')}」"
    else:
        advice = f"首选「{best.get('name')}」"
        if passed:
            advice += "；" + "、".join(f"「{r.get('name')}」胜率虽高但" +
                                      {"too_few": "样本太少，不可信", "suspect": "数据存疑"}.get(r["thin"], "样本偏少")
                                      for r in passed)
    if best is not None and best.get("basis") == "tier_only":
        advice += "（仅按层级）"
    if not hero_id:
        advice += "（未识别英雄，按全英雄数据）"

    return {
        "hero_id": hero_id,
        "base_win": base,
        "slots": results,
        "best_index": best["index"] if best else None,
        "advice": advice,
        "sources": {"tencent_date": (hero or {}).get("date"), "huya_patch": store.huya.get("patch"),
                    "aramgg_patch": ag_patch, "aramgg_date": (ag or {}).get("win_date"), "win_source": ag_name,
                    "huya_date": store.huya.get("date"), "patch": store.static.get("patch")},
    }
