"""公开数据源的最小 HTTP 封装：超时、重试、限速。"""

from __future__ import annotations

import json
import threading
import time

import requests

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)

_session = requests.Session()
_session.headers.update({"User-Agent": UA, "Accept": "application/json,*/*"})
_lock = threading.Lock()
_last_request = 0.0
# 两次请求之间至少间隔多少秒；所有数据源共用，保证低频。
MIN_INTERVAL = 0.35


class FetchError(RuntimeError):
    pass


def _throttle() -> None:
    global _last_request
    with _lock:
        wait = _last_request + MIN_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_request = time.monotonic()


def get(url: str, *, timeout: float = 20, retries: int = 2, referer: str | None = None) -> requests.Response:
    headers = {"Referer": referer} if referer else None
    last: Exception | None = None
    for attempt in range(retries + 1):
        _throttle()
        try:
            r = _session.get(url, timeout=timeout, headers=headers)
            if r.status_code == 200:
                return r
            last = FetchError(f"HTTP {r.status_code} {url}")
            if r.status_code in (403, 404):
                break
        except requests.RequestException as e:  # 连接错误、超时
            last = e
        time.sleep(0.8 * (attempt + 1))
    raise FetchError(str(last))


def get_json(url: str, **kw):
    r = get(url, **kw)
    # 腾讯部分 .js 文件本身就是 JSON；统一用 utf-8 解。
    return json.loads(r.content.decode("utf-8-sig"))


def head_ok(url: str, timeout: float = 10) -> bool:
    _throttle()
    try:
        r = _session.head(url, timeout=timeout, allow_redirects=True)
        return r.status_code == 200
    except requests.RequestException:
        return False
