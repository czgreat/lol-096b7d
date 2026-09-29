"""游戏机端的数据层：优先从数据服务读取，数据服务不可用时退回直连公开数据源。

数据服务接口（见 lolhex/service）：
  GET {base}/api/bundle      静态资料 + 腾讯榜单 + 虎牙总体胜率 + 数据状态
  GET {base}/api/hero/{id}   单英雄：腾讯海克斯/出装/加点 + ARAMGG + 虎牙
与 DataStore 接口一致，recommend / panel 不需要区分数据从哪来。
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import requests

from .store import DataStore, _read, _write

log = logging.getLogger(__name__)


class RemoteStore(DataStore):
    def __init__(self, root: Path, base_url: str, refresh_hours: float = 6.0):
        super().__init__(root, refresh_hours, huya_enabled=True, aramgg_key="")
        self.base_url = base_url.rstrip("/")
        self._remote_heroes: dict[str, dict] = {}
        self.remote_ok: bool | None = None
        self._remote_status: dict = {}

    def _get(self, path: str, timeout: float = 20):
        r = requests.get(self.base_url + path, timeout=timeout)
        r.raise_for_status()
        return r.json()

    def refresh(self, force: bool = False) -> None:
        try:
            b = self._get("/api/bundle", timeout=30)
            with self._lock:
                self.static, self.ranks = b["static"], b["ranks"]
                self.huya = {**self.huya, **b["huya"]}
                self._remote_status = b.get("status") or {}
                if b.get("aramgg_config"):
                    self._aramgg_config = b["aramgg_config"]
                _write(self.root / "static.json", self.static)
                _write(self.root / "ranks.json", self.ranks)
                _write(self.root / "huya_meta.json", b["huya"])
            self.remote_ok, self.last_error = True, None
        except Exception as e:
            log.warning("数据服务不可用，改为直连公开数据源：%s", e)
            self.remote_ok = False
            super().refresh(force)

    def _remote_hero(self, hero_id: str) -> dict | None:
        cached = self._remote_heroes.get(hero_id) or _read(self.root / "remote_hero" / f"{hero_id}.json")
        fresh = cached and time.time() - cached.get("_at", 0) < self.refresh_s \
            and cached.get("tencent", {}).get("patch") == self.static.get("patch")
        if not fresh and self.remote_ok is not False:
            try:
                cached = {**self._get(f"/api/hero/{hero_id}"), "_at": time.time()}
                _write(self.root / "remote_hero" / f"{hero_id}.json", cached)
            except Exception as e:
                log.info("数据服务单英雄 %s 获取失败：%s", hero_id, e)
        if cached:
            self._remote_heroes[hero_id] = cached
        return cached

    def hero(self, hero_id: str, allow_network: bool = True) -> dict | None:
        hero_id = str(hero_id)
        r = self._remote_hero(hero_id) if allow_network else self._remote_heroes.get(hero_id)
        if r and r.get("tencent"):
            return r["tencent"]
        return super().hero(hero_id, allow_network)

    def huya_hero(self, hero_id: str) -> dict | None:
        r = self._remote_heroes.get(str(hero_id)) or self._remote_hero(str(hero_id))
        if r and "huya" in r:
            return r["huya"]
        return super().huya_hero(hero_id)

    def aramgg_hero(self, hero_id: str, allow_network: bool = True) -> dict | None:
        r = self._remote_heroes.get(str(hero_id)) or (self._remote_hero(str(hero_id)) if allow_network else None)
        return (r or {}).get("aramgg")

    def hexdata_hero(self, hero_id: str) -> dict | None:
        r = self._remote_heroes.get(str(hero_id)) or self._remote_hero(str(hero_id))
        h = (r or {}).get("hexdata")
        patch = self.static.get("patch")
        return h if h and (not patch or h.get("patch") == patch) else None

    def status(self) -> dict:
        s = {**super().status(), **{k: v for k, v in self._remote_status.items()
                                    if k.startswith(("aramgg", "hexdata"))}}
        s["source"] = "nas" if self.remote_ok else ("direct" if self.remote_ok is False else "pending")
        s["nas"] = self.base_url
        return s


def bundle(store: DataStore) -> dict:
    """数据服务端：给游戏机的整包数据（虎牙只带总体胜率与版本信息，单英雄部分走 /api/hero）。"""
    hy = {k: v for k, v in store.huya.items() if k != "heroes"}
    return {"static": store.static, "ranks": store.ranks, "huya": hy,
            "aramgg_config": {k: v for k, v in store._aramgg_config.items() if k != "remaining"},
            "status": store.status()}


def hero_payload(store: DataStore, hero_id: str) -> dict:
    return {"tencent": store.hero(hero_id, allow_network=False) or store.hero(hero_id),
            "aramgg": store.aramgg_hero(hero_id, allow_network=False),
            "hexdata": store.hexdata_hero(hero_id),
            "huya": store.huya_hero(hero_id)}


def dumps(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, default=str, separators=(",", ":")).encode("utf-8")
