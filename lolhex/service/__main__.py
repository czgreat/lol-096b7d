"""数据服务：python -m lolhex.service [--port 8080] [--data /data]

- 每 6 小时刷新静态资料、腾讯榜单、虎牙（有新版本立即存档）；
- 每天把全部英雄的腾讯单英雄数据拉一遍（每个英雄间隔几秒，低频）；
- ARAMGG 按发布自动抓：每 30 分钟看一次 config.json（不扣额度），ARAMGG 发布了新数据就按英雄热度
  把全部英雄抓一遍（每个 1 点，另加 1 点全英雄层级，共约 174 点，一天 200 点够用）；额度低于保留数就停，
  第二天接着补。新发布先抽查最热门的英雄：胜率日期和样本都没变就沿用旧数据，只花 1～2 点；请求失败本轮即停。
  没有新发布不花额度。游戏机查英雄、看板只读缓存，从不实时抓。
  也可以手动：POST /api/aramgg/fetch?limit=N。环境变量 ARAMGG_AUTO=0 关掉自动，只留手动；
- 每天存一份完整快照到 <data>/snapshots/<日期>/；
- 提供游戏机用的接口与网页看板（只读，不接触任何游戏客户端）。

ARAMGG Key：环境变量 ARAMGG_API_KEY，或文件 <data>/secrets/aramgg_key（不进仓库）。
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import os
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from ..data.remote import bundle, dumps, hero_payload
from ..data.store import DataStore
from ..panel import hero_panel

log = logging.getLogger("lolhex.service")
HERO_PAUSE_S = 3.0          # 全量拉单英雄时每个英雄之间的间隔
FULL_PASS_HOURS = 24        # 单英雄全量刷新周期


def _aramgg_key(data_dir: Path) -> str:
    key = os.environ.get("ARAMGG_API_KEY", "").strip()
    f = data_dir / "secrets" / "aramgg_key"
    if not key and f.exists():
        key = f.read_text(encoding="utf-8").strip()
    return key


def _same_wins(old: dict | None, new: dict | None) -> bool:
    """两份单英雄数据的胜率是否同一批：胜率日期和样本场次都一样。"""
    return bool(old and new and new.get("win_date")) and all(
        old.get(k) == new.get(k) for k in ("win_date", "sample_games"))


class Syncer:
    def __init__(self, store: DataStore, data_dir: Path):
        self.store = store
        self.aramgg_auto = False  # ARAMGG 有新发布就自动抓；只有同步线程会抓，查英雄、看板从不实时抓
        self._ar_lock = threading.Lock()
        self.data_dir = data_dir
        self.state = {"started_at": time.time(), "last_refresh": None, "last_full_pass": None,
                      "full_pass_progress": None, "last_snapshot": None, "errors": []}
        self._stop = threading.Event()
        p = data_dir / "sync_state.json"
        if p.exists():
            try:
                self.state.update({k: v for k, v in json.loads(p.read_text(encoding="utf-8")).items()
                                   if k in ("last_full_pass", "last_snapshot")})
            except ValueError:
                pass

    def _save(self):
        (self.data_dir / "sync_state.json").write_text(json.dumps(self.state, ensure_ascii=False),
                                                       encoding="utf-8")

    def _err(self, msg: str):
        log.warning(msg)
        self.state["errors"] = (self.state["errors"] + [{"at": time.time(), "msg": msg}])[-20:]

    def run(self):
        while not self._stop.is_set():
            try:
                self.store.refresh()
                self.state["last_refresh"] = time.time()
                if self.store.last_error:
                    self._err(f"刷新：{self.store.last_error}")
                if time.time() - (self.state.get("last_full_pass") or 0) > FULL_PASS_HOURS * 3600:
                    self.full_pass()
                if self.aramgg_auto:
                    self.aramgg_pass()
                else:
                    self.aramgg_progress()
                self._save()
            except Exception as e:
                self._err(f"同步异常：{e}")
            self._stop.wait(1800)

    def _hero_order(self) -> list[str]:
        """按腾讯出场率从高到低：常玩的英雄优先拿到 ARAMGG 数据。"""
        ranks = self.store.ranks.get("heroes") or {}
        return sorted(self.store.heroes, key=lambda h: -((ranks.get(h) or {}).get("pick") or 0))

    def full_pass(self):
        heroes = self._hero_order()
        for i, hid in enumerate(heroes, 1):
            if self._stop.is_set():
                return
            self.store.hero(hid)
            self.state["full_pass_progress"] = f"{i}/{len(heroes)}"
            self._stop.wait(HERO_PAUSE_S)
        self.state["last_full_pass"] = time.time()
        self.snapshot()

    def aramgg_pass(self, limit: int | None = None, manual: bool = False) -> int:
        """补拉缺少或过期的 ARAMGG 单英雄数据，最多 limit 个，额度不够就停。返回实际请求的英雄数。"""
        if not self.store.aramgg_key or not self._ar_lock.acquire(blocking=False):
            return 0
        n = 0
        try:
            self.store.aramgg_release()  # 看 ARAMGG 有没有发布新数据（不扣额度）
            self.store.aramgg_champions(manual=True)  # 英雄层级，每次发布 1 credit
            todo = sum(1 for h in self.store.heroes if not self.store.aramgg_fresh(h))
            if todo and not manual and not self.store.aramgg_low():
                log.info("ARAMGG 数据 %s：%d 个英雄待抓，剩余额度 %s",
                         self.store.aramgg_release(), todo, self.store.aramgg_remaining)
            stale = [h for h in self._hero_order() if not self.store.aramgg_fresh(h)]
            # 新发布先抽查最热门的一个有旧数据的英雄：胜率日期和样本场次都没变，说明胜率没更新
            # （例如只换了腾讯选取率），其余英雄直接沿用旧数据，不花额度。
            probe = next((h for h in stale if self.store.aramgg_cached(h)), None)
            if probe and not self.store.aramgg_low() and (limit is None or limit > 0):
                old = self.store.aramgg_cached(probe)
                new = self.store.aramgg_hero(probe, manual=True)
                n += 1
                if not self.store.aramgg_fresh(probe):
                    return n  # 请求失败（网络、额度）：这一轮先停
                if _same_wins(old, new):
                    kept = sum(self.store.aramgg_adopt(h) for h in stale if h != probe)
                    log.info("ARAMGG 新发布 %s 抽查英雄 %s：胜率日期 %s、样本 %s 场都没变，其余 %d 个英雄沿用旧数据",
                             self.store.aramgg_release(), probe, new.get("win_date"), new.get("sample_games"), kept)
                self._stop.wait(HERO_PAUSE_S)
            for hid in self._hero_order():
                if self._stop.is_set() or self.store.aramgg_low() or (limit is not None and n >= limit):
                    break
                if not self.store.aramgg_fresh(hid):
                    self.store.aramgg_hero(hid, manual=True)
                    n += 1
                    if not self.store.aramgg_fresh(hid):
                        break  # 请求失败（网络、接口变了）：这一轮先停，别每个英雄都失败一次
                    self._stop.wait(HERO_PAUSE_S)
            if manual:
                log.info("ARAMGG 手动抓取：%d 个英雄，剩余额度 %s", n, self.store.aramgg_remaining)
        finally:
            self._ar_lock.release()
            self.aramgg_progress()
        return n

    def aramgg_progress(self):
        heroes = self.store.heroes
        have = sum(1 for h in heroes if self.store.aramgg_fresh(h))
        self.state["aramgg_progress"] = f"{have}/{len(heroes)}"
        self.state["aramgg_auto"] = self.aramgg_auto

    def snapshot(self):
        day = datetime.now().strftime("%Y%m%d")
        d = self.data_dir / "snapshots" / day
        d.mkdir(parents=True, exist_ok=True)
        (d / "bundle.json.gz").write_bytes(gzip.compress(dumps(bundle(self.store))))
        heroes = {hid: hero_payload(self.store, hid) for hid in self.store.heroes}
        (d / "heroes.json.gz").write_bytes(gzip.compress(dumps(heroes)))
        self.state["last_snapshot"] = day
        log.info("快照已保存：%s", d)


def make_handler(store: DataStore, syncer: Syncer, k: int):
    class H(BaseHTTPRequestHandler):
        server_version = "lolhex-service"

        def log_message(self, fmt, *args):
            log.debug("http " + fmt, *args)

        def _send(self, code, body: bytes, ctype="application/json; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/health":
                # 服务在线即 ok；首次同步完成前 ready 为 false
                return self._send(200, dumps({"ok": True, "ready": bool(store.static.get("heroes")),
                                              "patch": store.static.get("patch")}))
            if path == "/docs":
                return self._send(200, (__doc__ or "").encode("utf-8"), "text/plain; charset=utf-8")
            if path in ("/", "/index.html"):
                return self._send(200, resources.files("lolhex.service").joinpath("dashboard.html").read_bytes(),
                                  "text/html; charset=utf-8")
            if path == "/api/status":
                return self._send(200, dumps({"data": store.status(), "sync": syncer.state}))
            if path == "/api/bundle":
                return self._send(200, dumps(bundle(store)))
            if path == "/api/heroes":
                ranks = store.ranks.get("heroes") or {}
                hs = [{**h, "rank": ranks.get(hid)} for hid, h in store.heroes.items()]
                return self._send(200, dumps(sorted(hs, key=lambda h: (h.get("rank") or {}).get("rank") or 999)))
            if path.startswith("/api/hero/"):
                parts = path.split("/")
                hid = store.resolve_hero(unquote(parts[3]))
                if not hid:
                    return self._send(404, dumps({"error": "not_found"}))
                if len(parts) > 4 and parts[4] == "panel":
                    return self._send(200, dumps(hero_panel(store, hid, k)))
                return self._send(200, dumps(hero_payload(store, hid)))
            self._send(404, dumps({"error": "not_found"}))

        def do_POST(self):
            u = urlparse(self.path)
            if u.path != "/api/aramgg/fetch":
                return self._send(404, dumps({"error": "not_found"}))
            q = parse_qs(u.query)
            try:
                limit = int((q.get("limit") or ["0"])[0])
            except ValueError:
                limit = 0
            if limit <= 0:
                return self._send(400, dumps({"error": "需要 limit=N（要抓的英雄数，每个约 2 点额度）"}))
            if not store.aramgg_key:
                return self._send(400, dumps({"error": "未配置 ARAMGG Key"}))
            threading.Thread(target=syncer.aramgg_pass, kwargs={"limit": limit, "manual": True},
                             name="aramgg-manual", daemon=True).start()
            return self._send(202, dumps({"started": True, "limit": limit,
                                          "remaining": store.aramgg_remaining}))

    return H


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="lolhex.service", description="海克斯大乱斗数据服务（数据服务）")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    ap.add_argument("--data", default=os.environ.get("LOLHEX_DATA", "/data"))
    ap.add_argument("--no-sync", action="store_true", help="只提供接口，不主动抓取（调试用）")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    data_dir = Path(args.data)
    data_dir.mkdir(parents=True, exist_ok=True)
    key = _aramgg_key(data_dir)
    store = DataStore(data_dir / "store", refresh_hours=6.0, aramgg_key=key)
    store.aramgg_auto = False  # 服务里只有同步线程抓 ARAMGG，接口请求只读缓存
    syncer = Syncer(store, data_dir)
    syncer.aramgg_auto = os.environ.get("ARAMGG_AUTO", "1").strip() != "0"
    log.info("ARAMGG：%s，%s", "已配置 Key" if key else "未配置 Key，跳过",
             "有新发布就自动抓全部英雄" if syncer.aramgg_auto else "只手动抓取（POST /api/aramgg/fetch?limit=N）")
    if not args.no_sync:
        threading.Thread(target=syncer.run, name="sync", daemon=True).start()
    httpd = ThreadingHTTPServer(("0.0.0.0", args.port), make_handler(store, syncer, 300))
    log.info("数据服务：http://0.0.0.0:%d/", args.port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
