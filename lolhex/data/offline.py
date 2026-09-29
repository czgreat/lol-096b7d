"""离线版数据层：只读安装包自带的数据快照（bundled-data），从不联网更新。

给朋友用的发布版：数据固定在打包时的版本（16.19），不需要数据服务，也不需要 ARAMGG Key。
与 DataStore 接口一致，recommend / panel 不需要区分数据从哪来。
"""

from __future__ import annotations

import sys
from pathlib import Path

from .store import DataStore, _read


def bundled_dir() -> Path | None:
    """安装包里（PyInstaller 解包目录）或源码仓库根目录下的 bundled-data。"""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    d = base / "bundled-data"
    return d if (d / "static.json").exists() else None


class OfflineStore(DataStore):
    def __init__(self, root: Path):
        super().__init__(root, refresh_hours=1e9, huya_enabled=False)
        self.aramgg_auto = False

    def refresh(self, force: bool = False) -> None:
        self.last_error = None

    def hero(self, hero_id: str, allow_network: bool = True) -> dict | None:
        return super().hero(hero_id, allow_network=False)

    def aramgg_release(self) -> str | None:
        return self._release_key()

    def aramgg_hero(self, hero_id: str, allow_network: bool = True, reserve: int | None = None,
                    manual: bool = False) -> dict | None:
        hero_id = str(hero_id)
        cached = self._aramgg.get(hero_id) or _read(self.root / "aramgg" / f"{hero_id}.json")
        if cached:
            self._aramgg[hero_id] = cached
        return cached

    def status(self) -> dict:
        return {**super().status(), "source": "offline", "aramgg_enabled": True}
