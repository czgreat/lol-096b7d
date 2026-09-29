"""本地数据缓存：抓取、落盘、按需刷新，并对外提供统一的查询接口。

目录：<app_home>/data/
  static.json        英雄、海克斯字典、装备、版本
  ranks.json         腾讯英雄榜、海克斯总榜
  huya.json          虎牙英雄×海克斯胜率（已裁剪）
  hero/<id>.json     单英雄海克斯/出装/加点（按需抓取）

网络失败时继续使用旧缓存，并在 status() 里标明来源日期，界面据此提示"数据可能过期"。
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from . import aramgg, hexdata, http, huya, tencent

log = logging.getLogger(__name__)

CDRAGON_AUG = ("https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/"
               "global/zh_cn/v1/cherry-augments.json")
CDRAGON_RARITY = {"kSilver": "silver", "kGold": "gold", "kPrismatic": "prismatic"}


_ALIASES: dict[str, list[str]] | None = None


def hexdata_aliases() -> dict[str, list[str]]:
    """玩家常用叫法，随安装包带：hero_aliases.json（数据来源：Hexdata，hexdata.com.cn）
    + hero_nicknames.json（网上常见外号，人工整理）。"""
    global _ALIASES
    if _ALIASES is None:
        _ALIASES = {}
        for name, key in (("hero_aliases.json", "aliases"), ("hero_nicknames.json", "nicknames")):
            try:
                d = json.loads(Path(__file__).with_name(name).read_text(encoding="utf-8"))[key]
            except (OSError, ValueError, KeyError):
                continue
            for hid, names in d.items():
                _ALIASES.setdefault(hid, []).extend(names)
    return _ALIASES


def _read(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


class DataStore:
    def __init__(self, root: Path, refresh_hours: float = 6.0, huya_enabled: bool = True,
                 aramgg_key: str = ""):
        self.root = Path(root)
        self.refresh_s = refresh_hours * 3600
        self.huya_enabled = huya_enabled
        self._lock = threading.RLock()
        self.static: dict = _read(self.root / "static.json") or {}
        self.ranks: dict = _read(self.root / "ranks.json") or {}
        self.huya: dict = _read(self.root / "huya.json") or {}
        self._heroes: dict[str, dict] = {}
        self.last_error: str | None = None
        self.aramgg_key = aramgg_key
        self.aramgg_auto = True  # False：只在手动抓取时联网，平时只读缓存（额度有限）
        self._aramgg: dict[str, dict] = {}
        self._aramgg_config: dict = _read(self.root / "aramgg_config.json") or {}
        self.aramgg_remaining: int | None = self._aramgg_config.get("remaining")
        self._hexdata: dict[str, dict] | None = None
        self._hexdata_mtime: float | None = None

    # ---------- 刷新 ----------

    def _stale(self, blob: dict) -> bool:
        return not blob or time.time() - blob.get("fetched_at", 0) > self.refresh_s

    def refresh(self, force: bool = False) -> None:
        errors = []
        for name, fn, blob in (("static", self._refresh_static, self.static),
                               ("ranks", self._refresh_ranks, self.ranks),
                               ("huya", self._refresh_huya, self.huya)):
            if name == "huya" and not self.huya_enabled:
                continue
            if force or self._stale(blob):
                try:
                    fn()
                except Exception as e:  # 单个来源失败不影响其他
                    log.warning("刷新 %s 失败：%s", name, e)
                    errors.append(f"{name}: {e}")
        self.last_error = "; ".join(errors) or None

    def _refresh_static(self) -> None:
        heroes = tencent.parse_hero_list(tencent.fetch_hero_list())
        augments = tencent.parse_kiwi_augments(tencent.fetch_kiwi_augments())
        items = tencent.parse_items(tencent.fetch_items())
        try:
            spells = tencent.parse_summoner_spells(tencent.fetch_summoner_spells())
        except Exception as e:
            log.info("召唤师技能列表获取失败：%s", e)
            spells = self.static.get("spells", {})
        try:
            versions = tencent.fetch_versions()
        except Exception:
            versions = self.static.get("versions", [])
        try:
            self._merge_cdragon(augments)
        except Exception as e:
            log.info("CommunityDragon 补充失败：%s", e)
        patch = versions[0]["name"] if versions else self.static.get("patch", "")
        with self._lock:
            if patch and patch != self.static.get("patch"):
                self._heroes.clear()  # 新版本：单英雄缓存作废
            self.static = {"fetched_at": time.time(), "patch": patch, "versions": versions[:6],
                           "heroes": heroes, "augments": augments, "items": items, "spells": spells}
            _write(self.root / "static.json", self.static)

    @staticmethod
    def _merge_cdragon(augments: dict) -> None:
        """腾讯 kiwi 列表偶尔缺条目，用 CommunityDragon 中文数据补名字和稀有度。"""
        raw = http.get_json(CDRAGON_AUG, timeout=30)
        for a in raw:
            aid = str(a.get("id"))
            name_id = str(a.get("augmentNameId", ""))
            icon = str(a.get("augmentSmallIconPath", ""))
            is_mayhem = name_id.startswith("ARAM_") or "kiwi" in icon.lower()
            if aid in augments or not is_mayhem or not a.get("nameTRA"):
                continue
            augments[aid] = {"id": aid, "name": a["nameTRA"].strip(), "en": name_id,
                             "rarity": CDRAGON_RARITY.get(a.get("rarity"), "unknown"),
                             "desc": "", "icon": "", "modes": ["KIWI"], "source": "cdragon"}

    def _refresh_ranks(self) -> None:
        adate, augs = tencent.parse_augment_rank(tencent.fetch_augment_rank())
        hdate, heroes = "", {}
        # 英雄榜必须带统计日期：先用海克斯榜的日期，再依次往前试几天。
        start = datetime.strptime(adate, "%Y%m%d") if adate else datetime.now()
        for back in range(4):
            day = (start - timedelta(days=back)).strftime("%Y%m%d")
            hdate, heroes = tencent.parse_hero_rank(tencent.fetch_hero_rank(day))
            if heroes:
                hdate = hdate or day
                break
        with self._lock:
            self.ranks = {"fetched_at": time.time(), "date": hdate or adate,
                          "heroes": heroes, "augments": augs}
            _write(self.root / "ranks.json", self.ranks)
            # 腾讯只给当前的海克斯总体胜率，不给历史；每天存一份，换版本时才能精确比较改动。
            if adate:
                arch = self.root / "tencent_archive" / f"augment_rank_{adate}.json"
                if not arch.exists():
                    _write(arch, {"date": adate, "patch": self.static.get("patch"), "augments": augs})

    def _refresh_huya(self) -> None:
        latest = huya.discover_version(self.huya.get("version"))
        if latest is None:
            raise http.FetchError("虎牙数据版本探测失败")
        if latest == self.huya.get("version") and self.huya.get("augment_global"):
            self.huya["fetched_at"] = time.time()
            _write(self.root / "huya.json", self.huya)
            return
        data = huya.fetch(latest, self.root / "huya_archive")
        data["fetched_at"] = time.time()
        with self._lock:
            self.huya = data
            _write(self.root / "huya.json", data)

    # ---------- 查询 ----------

    @property
    def augments(self) -> dict[str, dict]:
        return self.static.get("augments", {})

    @property
    def heroes(self) -> dict[str, dict]:
        return self.static.get("heroes", {})

    @property
    def items(self) -> dict[str, dict]:
        return self.static.get("items", {})

    @property
    def spells(self) -> dict[str, dict]:
        return self.static.get("spells", {})

    def mayhem_augments(self) -> dict[str, dict]:
        """用于识别匹配的字典：只要大乱斗（KIWI）海克斯，排除纯斗魂竞技场条目。"""
        out = {}
        for aid, a in self.augments.items():
            modes = a.get("modes") or []
            if not modes or any(m.startswith("KIWI") for m in modes):
                out[aid] = a
        return out

    def hero_terms(self, hid: str) -> list[str]:
        """能搜到这个英雄的所有叫法：名字、称号、英文名、腾讯关键词（含拼音缩写）、玩家叫法。"""
        h = self.heroes.get(hid) or {}
        raw = [h.get("name"), h.get("nick"), h.get("alias"), *(h.get("keywords") or "").split(","),
               *hexdata_aliases().get(hid, [])]
        out, seen = [], set()
        for t in raw:
            t = (t or "").strip()
            if t and t.lower() not in seen:
                seen.add(t.lower())
                out.append(t)
        return out

    def resolve_hero(self, key: str | int | None) -> str | None:
        """按 heroId / 英文 alias / 中文名 / 称号 / 2999 的 rawChampionName 找英雄；
        再按别名（腾讯关键词、玩家叫法）精确匹配。"""
        if key in (None, "", 0, "0"):
            return None
        k = str(key).strip()
        if k in self.heroes:
            return k
        if k.startswith("game_character_displayname_"):
            k = k[len("game_character_displayname_"):]
        kl = k.lower()
        for hid, h in self.heroes.items():
            if kl in ((h.get("alias") or "").lower(), (h.get("name") or "").lower(),
                      (h.get("nick") or "").lower()):
                return hid
        for hid in self.heroes:
            if kl in (t.lower() for t in self.hero_terms(hid)):
                return hid
        for hid, h in self.heroes.items():
            full = f"{h.get('nick', '')} {h.get('name', '')}".lower()
            if kl and kl in full:
                return hid
        if not kl.isascii():  # 中文外号的一部分，如"风男"→快乐风男
            for hid in self.heroes:
                if any(kl in t for t in self.hero_terms(hid) if not t.isascii()):
                    return hid
        return None

    def hero(self, hero_id: str, allow_network: bool = True) -> dict | None:
        """单英雄完整数据（腾讯 + 虎牙合并）。优先内存，再磁盘，过期则联网。"""
        hero_id = str(hero_id)
        with self._lock:
            cached = self._heroes.get(hero_id)
        path = self.root / "hero" / f"{hero_id}.json"
        if cached is None:
            cached = _read(path)
        patch = self.static.get("patch")
        fresh = cached and not self._stale(cached) and cached.get("patch") == patch
        if not fresh and allow_network:
            try:
                data = tencent.parse_hero_hex(tencent.fetch_hero_hex(hero_id))
                try:
                    data["spells"] = tencent.parse_hero_spells(tencent.fetch_hero_file(hero_id))
                except Exception:
                    data["spells"] = (cached or {}).get("spells", {})
                data["fetched_at"] = time.time()
                data["patch"] = patch
                _write(path, data)
                cached = data
            except Exception as e:
                log.warning("获取英雄 %s 数据失败：%s", hero_id, e)
                self.last_error = f"hero {hero_id}: {e}"
        if cached is None:
            return None
        with self._lock:
            self._heroes[hero_id] = cached
        return cached

    # ---------- ARAMGG ----------

    AR_MIN_REMAINING = 20  # 额度低于这个数就不再请求，给手动查询留余量
    AR_RETRY_S = 3600  # 额度用完被拒后，隔多久再试
    AR_CONFIG_CHECK_S = 3600  # 多久看一次 ARAMGG 是否发布了新数据（config.json 不扣额度）

    def aramgg_release(self) -> str | None:
        """ARAMGG 当前发布标识 = dataVersion@publishedAt（config.json 不扣额度，每小时查一次）。
        同一个 dataVersion 也可能重新发布（样本更新），所以带上发布时间。"""
        cfg = self._aramgg_config
        if time.time() - cfg.get("checked_at", 0) > self.AR_CONFIG_CHECK_S:
            try:
                c = aramgg.fetch_config()
                cfg.update(data_version=c.get("dataVersion"), patch=c.get("gamePatch"),
                           published_at=c.get("publishedAt") or c.get("generatedAt"), checked_at=time.time())
                _write(self.root / "aramgg_config.json", cfg)
            except Exception as e:
                log.info("ARAMGG config 获取失败：%s", e)
        return self._release_key()

    def _release_key(self) -> str | None:
        cfg = self._aramgg_config
        if not cfg.get("data_version"):
            return None
        return f"{cfg['data_version']}@{cfg.get('published_at') or ''}"

    @staticmethod
    def _ar_current(cached: dict | None, release: str | None) -> bool:
        return bool(cached) and (release is None or cached.get("release") == release)

    def aramgg_low(self, reserve: int | None = None) -> bool:
        """今天的额度是否已低于保留数。按剩余数算出来的低，等到日期变了再试；
        被 429 拒过的，每小时再试一次（被拒不扣额度，也不用猜 ARAMGG 按哪个时区重置）。"""
        reserve = self.AR_MIN_REMAINING if reserve is None else reserve
        cfg = self._aramgg_config
        if self.aramgg_remaining is None or self.aramgg_remaining >= reserve:
            return False
        if cfg.get("exhausted_at"):
            return time.time() - cfg["exhausted_at"] < self.AR_RETRY_S
        return time.strftime("%Y-%m-%d") == cfg.get("remaining_day")

    def aramgg_fresh(self, hero_id: str) -> bool:
        """本地已有当前 dataVersion 的数据（不联网，版本号取缓存值）。"""
        hero_id = str(hero_id)
        cached = self._aramgg.get(hero_id) or _read(self.root / "aramgg" / f"{hero_id}.json")
        return self._ar_current(cached, self._release_key())

    def aramgg_cached(self, hero_id: str) -> dict | None:
        """本地缓存的 ARAMGG 单英雄数据，不管是不是当前发布（不联网）。"""
        hero_id = str(hero_id)
        return self._aramgg.get(hero_id) or _read(self.root / "aramgg" / f"{hero_id}.json")

    def aramgg_adopt(self, hero_id: str) -> bool:
        """把旧发布的缓存直接标成当前发布（不花额度）。用于抽查证实新发布的胜率和样本没变时。"""
        hero_id = str(hero_id)
        cached = self.aramgg_cached(hero_id)
        release = self._release_key()
        if not cached or release is None:
            return False
        cached = {**cached, "adopted_from": cached.get("release"), "release": release,
                  "patch": self._aramgg_config.get("patch") or cached.get("patch")}
        _write(self.root / "aramgg" / f"{hero_id}.json", cached)
        self._aramgg[hero_id] = cached
        return True

    def aramgg_hero(self, hero_id: str, allow_network: bool = True, reserve: int | None = None,
                    manual: bool = False) -> dict | None:
        """单英雄 ARAMGG 海克斯数据。同一次发布只请求一次（1 credit），之后读缓存。
        reserve：额度低于它就不请求（默认 AR_MIN_REMAINING；玩家正在用的英雄可以放低）。
        aramgg_auto 关闭时只有 manual=True（手动抓取）才联网。"""
        hero_id = str(hero_id)
        if not self.aramgg_key:
            return None
        cached = self._aramgg.get(hero_id) or _read(self.root / "aramgg" / f"{hero_id}.json")
        if not allow_network or not (self.aramgg_auto or manual):
            if cached:
                self._aramgg[hero_id] = cached
            return cached
        release = self.aramgg_release()
        fresh = self._ar_current(cached, release)
        low = self.aramgg_low(reserve)
        if not fresh and not low:
            raw = self._ar_paid(aramgg.fetch_champion_augments, hero_id, what=f"英雄 {hero_id}")
            if raw is not None:
                cached = aramgg.parse_champion_augments(raw, self._aramgg_config.get("patch"))
                cached["champion_tier"] = (self.aramgg_champions(manual=manual).get(hero_id) or {}).get("tier")
                cached["fetched_at"] = time.time()
                cached["release"] = release
                _write(self.root / "aramgg" / f"{hero_id}.json", cached)
        if cached:
            self._aramgg[hero_id] = cached
        return cached

    def aramgg_champions(self, manual: bool = False) -> dict[str, dict]:
        """全英雄层级（1 credit，每次发布拉一次）。"""
        path = self.root / "aramgg_champions.json"
        cached = _read(path)
        release = self._release_key()
        if self._ar_current(cached, release) or not (self.aramgg_auto or manual) or self.aramgg_low():
            return (cached or {}).get("heroes") or {}
        raw = self._ar_paid(aramgg.fetch_champions_stats, what="全英雄统计")
        if raw is None:
            return (cached or {}).get("heroes") or {}
        cached = {"heroes": aramgg.parse_champions_stats(raw), "release": release, "fetched_at": time.time()}
        _write(path, cached)
        return cached["heroes"]

    def _ar_paid(self, fn, *args, what: str = ""):
        """扣额度的 ARAMGG 请求：记录剩余额度；额度用完或失败返回 None。"""
        try:
            raw, remaining = fn(*args, self.aramgg_key)
        except aramgg.QuotaExhausted as e:  # 额度用完是正常状态，不算错误
            log.info("%s，%d 分钟后再试", e, self.AR_RETRY_S // 60)
            self.aramgg_remaining = 0
            self._aramgg_config.update(remaining=0, remaining_day=time.strftime("%Y-%m-%d"),
                                       exhausted_at=time.time())
            _write(self.root / "aramgg_config.json", self._aramgg_config)
            return None
        except Exception as e:
            log.warning("ARAMGG %s 获取失败：%s", what, e)
            self.last_error = f"aramgg {what}: {e}"
            return None
        self.aramgg_remaining = remaining
        self._aramgg_config.update(remaining=remaining, remaining_day=time.strftime("%Y-%m-%d"))
        self._aramgg_config.pop("exhausted_at", None)
        _write(self.root / "aramgg_config.json", self._aramgg_config)
        return raw

    # ---------- Hexdata 快照 ----------

    def _hexdata_all(self) -> dict[str, dict]:
        """<store>/hexdata.json（人工放入的快照；文件更新后自动重读）。"""
        path = self.root / "hexdata.json"
        mtime = path.stat().st_mtime if path.exists() else None
        if mtime != self._hexdata_mtime:
            try:
                self._hexdata = hexdata.parse(_read(path) or {}) if mtime else {}
            except Exception as e:
                log.warning("Hexdata 快照解析失败：%s", e)
                self._hexdata = {}
            self._hexdata_mtime = mtime
        return self._hexdata or {}

    def hexdata_hero(self, hero_id: str) -> dict | None:
        """当前游戏版本的 Hexdata 单英雄数据；版本对不上（快照过期）返回 None，退回 ARAMGG。"""
        h = self._hexdata_all().get(str(hero_id))
        patch = self.static.get("patch")
        return h if h and (not patch or h.get("patch") == patch) else None

    def win_data(self, hero_id: str, allow_network: bool = True) -> dict | None:
        """单英雄 × 海克斯胜率：当前版本的 Hexdata 优先（国服、样本约 7 倍），没有就用 ARAMGG。"""
        return self.hexdata_hero(hero_id) or self.aramgg_hero(hero_id, allow_network=allow_network)

    def huya_hero(self, hero_id: str) -> dict | None:
        return (self.huya.get("heroes") or {}).get(str(hero_id))

    def augment_drift(self) -> dict[str, float]:
        """虎牙快照版本 → 腾讯当前版本，每个海克斯总体胜率的变化（百分点）。
        两边都有总体胜率才计算；虎牙没有的新海克斯不在结果里。"""
        old = self.huya.get("augment_global") or {}
        now = self.ranks.get("augments") or {}
        out = {}
        for aid, w0 in old.items():
            w1 = (now.get(aid) or {}).get("win")
            if w0 is not None and w1 is not None:
                out[aid] = round((w1 - w0) * 100, 2)
        return out

    def status(self) -> dict:
        return {
            "patch": self.static.get("patch"),
            "static_at": self.static.get("fetched_at"),
            "tencent_date": self.ranks.get("date"),
            "ranks_at": self.ranks.get("fetched_at"),
            "huya_version": self.huya.get("version"),
            "huya_patch": self.huya.get("patch"),
            "huya_date": self.huya.get("date"),
            "huya_lag": self.huya.get("patch") != self.static.get("patch"),
            "aramgg_enabled": bool(self.aramgg_key),
            "aramgg_patch": self._aramgg_config.get("patch"),
            "aramgg_version": self._aramgg_config.get("data_version"),
            "aramgg_remaining": self.aramgg_remaining,
            "hexdata_heroes": sum(1 for h in self._hexdata_all().values()
                                  if h.get("patch") == self.static.get("patch")),
            "hexdata_patch": next(iter(self._hexdata_all().values()), {}).get("patch"),
            "augments": len(self.augments),
            "heroes": len(self.heroes),
            "error": self.last_error,
        }
