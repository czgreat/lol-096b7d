"""虎牙「海斗工具」网页版的公开 CDN 数据。

页面 gametool.huya.com/league-of-legends/wiki 先通过虎牙 WUP 协议查询版本号，再从
fileserver.cdn.huya.com/game_tools/1-<toolId>-<ver>/<ver>/<key>.json 取明文 JSON。
这里不实现 WUP，而是从已知版本号往后逐个探测，版本号单调递增。

用途：补充「英雄 × 海克斯」的胜率与场次（腾讯单英雄接口只有选取率与层级）。
虎牙数据自称来自腾讯国服公开统计，版本通常比腾讯接口晚一些，界面上会标出版本与日期。
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

from . import http

TOOL_ID = "p81hl812"
BASE = "https://fileserver.cdn.huya.com/game_tools"
SEED_VERSION = 395  # 2026-09-25 实测
PROBE_AHEAD = 12


def url(version: int, key: str) -> str:
    return f"{BASE}/1-{TOOL_ID}-{version}/{version}/{key}.json"


def discover_version(known: int | None = None) -> int | None:
    """从 known（或种子）开始向后探测，返回最新可用版本；都不可用返回 None。"""
    start = max(known or 0, SEED_VERSION)
    latest = start if http.head_ok(url(start, "champion-list")) else None
    misses = 0
    v = start + 1
    while misses < PROBE_AHEAD:
        if http.head_ok(url(v, "champion-list")):
            latest, misses = v, 0
        else:
            misses += 1
        v += 1
    if latest is None and known:
        # 种子之前的版本可能已下线；向前少量回退。
        for v in range(start - 1, start - 6, -1):
            if http.head_ok(url(v, "champion-list")):
                return v
    return latest


def _pct(x) -> float | None:
    if x in (None, ""):
        return None
    try:
        return float(str(x).rstrip("%")) / 100
    except ValueError:
        return None


def parse_champion_detail(raw: list) -> dict:
    """→ {patch, date, heroes: {heroId: {win, pick, games, augments: {augId: {win, pick, games, tier}}}}}"""
    heroes: dict = {}
    patch = date = ""
    for c in raw:
        hid = str(c.get("championId"))
        patch = patch or str(c.get("version", ""))
        date = date or str(c.get("date", ""))
        augs = {}
        for a in c.get("augmentRecommendations", []) or []:
            augs[str(a.get("augmentId"))] = {
                "win": _pct(a.get("winRate")),
                "pick": _pct(a.get("pickRate")),
                "games": a.get("numGames") if isinstance(a.get("numGames"), int) else None,
                "tier": a.get("tier") or None,
            }
        heroes[hid] = {
            "win": _pct(c.get("winRate")),
            "pick": _pct(c.get("pickRate")),
            "games": c.get("numGames") if isinstance(c.get("numGames"), int) else None,
            "tier": c.get("tier") or None,
            "augments": augs,
        }
    return {"patch": patch, "date": date, "heroes": heroes}


def parse_augment_list(raw: list) -> dict[str, float]:
    """海克斯总体胜率（全英雄）：{augId: win}。用来和腾讯当前总体胜率比，判断版本改动。"""
    out = {}
    for a in raw:
        w = _pct(a.get("winRate"))
        if w is not None:
            out[str(a.get("augmentId"))] = w
    return out


ARCHIVE_KEYS = ("champion-list", "champion-detail", "augment-list", "augment-detail", "item-detail")


def fetch(version: int, archive_dir: Path | None = None) -> dict:
    """下载并解析；archive_dir 给出时把原始文件压缩存档（虎牙会删除旧版本）。"""
    raws = {}
    for key in ("champion-detail", "augment-list"):
        raws[key] = http.get(url(version, key), timeout=60).content
    if archive_dir is not None:
        target = archive_dir / str(version)
        target.mkdir(parents=True, exist_ok=True)
        for key in ARCHIVE_KEYS:
            dest = target / f"{key}.json.gz"
            if dest.exists():
                continue
            try:
                body = raws.get(key) or http.get(url(version, key), timeout=60).content
                dest.write_bytes(gzip.compress(body))
            except http.FetchError:
                pass
    data = parse_champion_detail(json.loads(raws["champion-detail"].decode("utf-8-sig")))
    data["augment_global"] = parse_augment_list(json.loads(raws["augment-list"].decode("utf-8-sig")))
    data["version"] = version
    return data
