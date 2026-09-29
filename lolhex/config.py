"""运行配置与本地目录。

配置文件：%APPDATA%\\lolhex\\config.json（可用环境变量 LOLHEX_HOME 改目录）。
首次运行会写出默认值，之后手改即可；未知键保留不动。
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


def app_home() -> Path:
    env = os.environ.get("LOLHEX_HOME")
    if env:
        home = Path(env)
    else:
        base = os.environ.get("APPDATA") or str(Path.home())
        home = Path(base) / "lolhex"
    home.mkdir(parents=True, exist_ok=True)
    return home


# 旧版默认值 → 升级时换成新默认值（用户手改过的不动）
OLD_DEFAULTS = {"scan_interval_ms": 700}


@dataclass
class Settings:
    # 数据服务地址；留空则直连公开数据源。
    nas_url: str = ""
    # 读取游戏内 2999 接口（Riot 官方只读、非 LCU）识别英雄与等级。默认关闭。
    use_liveclient: bool = False
    # 在悬浮层与看板显示胜率数值。关掉后只显示层级与排名。
    show_winrate: bool = True
    # 数据刷新间隔（小时）。腾讯统计按天更新，虎牙按版本更新。
    refresh_hours: float = 6.0
    # 是否合并虎牙公开 CDN 的英雄×海克斯胜率/场次。
    huya_enabled: bool = True
    # 已校准时，检查三张卡标题区域的间隔（毫秒）。画面没变只比一次缩略图（<1ms），
    # 变了才对三个标题做纯识别（约 3×12ms）。
    scan_interval_ms: int = 300
    # 未校准时，整块中部区域检测+识别的间隔（秒）。单次约 0.3–0.5s CPU。
    bootstrap_interval_s: float = 3.0
    # 海克斯名称模糊匹配的最低分（0–100）。
    match_threshold: float = 72.0
    # 模式未知时是否也扫描（例如 LCU 与 2999 都读不到时）。
    scan_when_mode_unknown: bool = True
    # 小样本平滑强度：先验场次 k。
    smoothing_games: int = 300
    # 仅在不用数据服务、直连时需要：ARAMGG Key（也可用环境变量 LOLHEX_ARAMGG_KEY）。
    aramgg_api_key: str = ""
    # 悬浮层开关（--headless 也会关闭）。
    overlay: bool = True
    # 悬浮按钮的位置：top-right / top-left。
    overlay_corner: str = "top-right"
    extra: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or app_home() / "config.json"
        data: dict = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
        known = {f.name for f in fields(cls)}
        # 旧版本写进配置文件的默认值：没手改过的跟着新默认值走
        changed = False
        for k, old in OLD_DEFAULTS.items():
            if data.get(k) == old:
                data.pop(k)
                changed = True
        s = cls(**{k: v for k, v in data.items() if k in known and k != "extra"})
        s.extra = {k: v for k, v in data.items() if k not in known}
        env_key = os.environ.get("LOLHEX_ARAMGG_KEY")
        if env_key:
            s.aramgg_api_key = env_key
        if changed or not path.exists():
            s.save(path)
        return s

    def save(self, path: Path | None = None) -> None:
        path = path or app_home() / "config.json"
        data = asdict(self)
        extra = data.pop("extra", {}) or {}
        data.update(extra)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
