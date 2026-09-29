"""ARAMGG 数据接口（data.dtodo.cn），需要 API Key。

- 单英雄海克斯统计 /data/champion-augments/{id}.json，每次 1 credit（免费每天 200，UTC 0 点恢复）；
  海克斯胜场/场次/胜率与 /champions/{id}.json（2 credits，多了出装）逐项一致，所以只用 1 credit 的。
- 全英雄统计 /data/champions-stats.json，1 credit：英雄层级（腾讯国服，按版本更新）。
- 单英雄详情 /api/v1/zh-CN/champions/{id}.json，每次 2 credits（保留解析，出装以后可能用）。
- 层级、排名、出场率来自腾讯国服；单英雄海克斯胜率来自 ARAMGG 客户端上传，
  满 255 局才给出，接口标注为 WORLD（跨服）。ARAMGG 自己的统计报告称约 96.7% 来自国服。
- /api/v1/zh-CN/config.json 不需要 Key、不扣额度，用它的 dataVersion 判断缓存是否过期。
"""

from __future__ import annotations

import json

import requests

from . import http

BASE = "https://data.dtodo.cn/api/v1/zh-CN"


class QuotaExhausted(http.FetchError):
    pass


def fetch_config() -> dict:
    return http.get_json(f"{BASE}/config.json", timeout=20)


def fetch_champion(hero_id: str, key: str) -> tuple[dict, int | None]:
    """2 credits → (原始 JSON, 今日剩余额度)。"""
    return _get_paid(f"{BASE}/champions/{hero_id}.json", key)


def fetch_champion_augments(hero_id: str, key: str) -> tuple[list, int | None]:
    """1 credit → (原始元组列表, 今日剩余额度)。"""
    return _get_paid(f"{BASE}/data/champion-augments/{hero_id}.json", key)


def fetch_champions_stats(key: str) -> tuple[list, int | None]:
    """1 credit → (全英雄统计, 今日剩余额度)。"""
    return _get_paid(f"{BASE}/data/champions-stats.json", key)


def _get_paid(url: str, key: str):
    http._throttle()
    try:
        r = http._session.get(url, timeout=30, headers={"Authorization": f"Bearer {key}"})
    except requests.RequestException as e:
        raise http.FetchError(str(e)) from e
    remaining = r.headers.get("x-credits-remaining")
    remaining = int(remaining) if remaining and remaining.isdigit() else None
    if r.status_code == 429:
        raise QuotaExhausted("ARAMGG 今日额度已用完")
    if r.status_code == 401:
        raise http.FetchError("ARAMGG API Key 无效")
    if r.status_code != 200:
        raise http.FetchError(f"ARAMGG HTTP {r.status_code}")
    return r.json(), remaining


def parse_champion(raw: dict) -> dict:
    """→ {patch, data_version, date, win_date, base_win, sample_win, augments: {id: {...}}}

    sample_win：ARAMGG 上传样本里该英雄的胜率（按各海克斯胜场/场次汇总），
    用它做基准算Δ，基准和海克斯胜率来自同一批对局。"""
    meta = raw.get("meta") or {}
    data = raw.get("data") or {}
    champ = (data.get("champion") or {}).get("stats") or {}
    augs = {}
    wins = games = 0
    win_date = None
    for a in data.get("augments") or []:
        s = a.get("stats") or {}
        aid = str(a.get("id"))
        w, g = s.get("wins"), s.get("games")
        augs[aid] = {
            "win": s.get("winRate") if s.get("winRateSource") else None,
            "wins": w, "games": g,
            "pick": s.get("pickRate"), "tier": s.get("tier"),
            "rank": s.get("rank"), "total": s.get("total"),
            "region": s.get("winRateRegion") or s.get("region"),
        }
        if isinstance(w, int) and isinstance(g, int) and g > 0:
            wins += w
            games += g
        win_date = win_date or s.get("winRateDate")
    return {
        "patch": meta.get("gamePatch"),
        "data_version": meta.get("dataVersion"),
        "date": champ.get("date"),
        "win_date": win_date,
        "base_win": champ.get("winRate"),
        "champion_tier": champ.get("tier"),
        "sample_win": wins / games if games else None,
        "sample_games": games,
        "augments": augs,
    }


def _num(v, cast=float):
    try:
        return cast(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def parse_champion_augments(raw: list, patch: str | None = None) -> dict:
    """/data/champion-augments/{id}.json → 与 parse_champion 相同的结构（数字字段原样是字符串）。"""
    row = raw[0] if raw else ["", "{}", None, None]
    data = json.loads(row[1] or "{}")
    augs = {}
    wins = games = 0
    win_date = None
    for aid, s in (data.get("augments") or {}).items():
        w, g = _num(s.get("num_win_games"), int), _num(s.get("num_games"), int)
        augs[str(aid)] = {
            "win": _num(s.get("win_rate")) if s.get("win_rate_source") else None,
            "wins": w, "games": g,
            "pick": _num(s.get("pick_rate")), "tier": _num(s.get("tier"), int),
            "rank": _num(s.get("rank"), int), "total": _num(s.get("total"), int),
            "region": s.get("win_rate_region") or data.get("region"),
        }
        if w is not None and g:
            wins += w
            games += g
        win_date = win_date or s.get("win_rate_date")
    return {
        "patch": patch or row[2],
        "data_version": None,
        "date": row[3],
        "win_date": win_date,
        "base_win": None,
        "champion_tier": None,
        "sample_win": wins / games if games else None,
        "sample_games": games,
        "augments": augs,
    }


def parse_champions_stats(raw: list) -> dict[str, dict]:
    """→ {英雄ID: {tier, win, pick, version, date}}"""
    return {str(x.get("championId")): {"tier": _num(x.get("tier"), int), "win": x.get("winRate"),
                                       "pick": x.get("pickRate"), "version": x.get("version"),
                                       "date": x.get("date")} for x in raw or []}
