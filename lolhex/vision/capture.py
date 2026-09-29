"""屏幕截取：只截需要的矩形区域，返回 BGR numpy 数组。

使用 mss（GDI BitBlt）：无边框/窗口化下可用；独占全屏可能截到黑屏，界面会提示改无边框。
"""

from __future__ import annotations

import threading

import numpy as np

from .window import Rect

_local = threading.local()


def _mss():
    inst = getattr(_local, "mss", None)
    if inst is None:
        import mss
        inst = mss.MSS() if hasattr(mss, "MSS") else mss.mss()
        _local.mss = inst
    return inst


def grab(rect: Rect) -> np.ndarray:
    shot = _mss().grab({"left": rect.left, "top": rect.top, "width": rect.width, "height": rect.height})
    arr = np.asarray(shot)  # BGRA
    return np.ascontiguousarray(arr[:, :, :3])


def is_blank(img: np.ndarray) -> bool:
    """全黑/几乎纯色：多半是独占全屏截不到。"""
    return img.size == 0 or float(img.std()) < 2.0
