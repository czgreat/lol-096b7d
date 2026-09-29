"""装备、召唤师技能的小图标：按需从腾讯 CDN 下载到本地，界面用本地文件显示。

界面线程只查本地文件，不等网络：没有就先返回 None（界面先显示文字），同时交给后台线程下载；
下载完成后 version 加一，界面据此重新渲染。
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import http

log = logging.getLogger(__name__)
MAX_AGE_S = 14 * 86400  # 图标很少变；两周后顺手重下一次，跟上版本改图


class IconCache:
    def __init__(self, folder: Path, workers: int = 4):
        self.folder = folder
        self.version = 0
        self._pending: set[str] = set()
        self._failed: dict[str, float] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="icons")

    def local(self, kind: str, key: str, url: str | None) -> str | None:
        """本地图标路径（给 Qt 富文本 <img> 用），还没有就后台下载并返回 None。"""
        if not key:
            return None
        path = self.folder / kind / f"{key}.png"
        fresh = path.exists() and time.time() - path.stat().st_mtime < MAX_AGE_S
        if not fresh and url:
            self._fetch(path, url)
        return path.as_posix() if path.exists() else None

    def _fetch(self, path: Path, url: str) -> None:
        tag = str(path)
        with self._lock:
            if tag in self._pending or time.time() - self._failed.get(tag, 0) < 600:
                return
            self._pending.add(tag)
        self._pool.submit(self._download, path, url, tag)

    def _download(self, path: Path, url: str, tag: str) -> None:
        try:
            if url.startswith("//"):
                url = "https:" + url
            r = http._session.get(url, timeout=15)
            if r.status_code != 200 or not r.content.startswith(b"\x89PNG"):
                raise ValueError(f"HTTP {r.status_code}")
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(r.content)
            tmp.replace(path)
            with self._lock:
                self.version += 1
        except Exception as e:
            log.info("图标下载失败 %s：%s", url, e)
            with self._lock:
                self._failed[tag] = time.time()
        finally:
            with self._lock:
                self._pending.discard(tag)
