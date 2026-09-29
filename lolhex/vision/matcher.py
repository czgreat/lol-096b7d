"""把 OCR 文本模糊匹配到已知名称（海克斯 / 英雄）。"""

from __future__ import annotations

import re
import unicodedata

from rapidfuzz import fuzz, process

_PUNCT = re.compile(r"[\s·•・:：,，.。!！?？'\"“”‘’()（）\[\]【】<>《》\-—_~～|/\\]+")


def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    return _PUNCT.sub("", s).lower()


class NameMatcher:
    def __init__(self, names: dict[str, str], threshold: float = 72.0):
        """names: {id: 显示名}。"""
        self.threshold = threshold
        self._ids: list[str] = []
        self._keys: list[str] = []
        for i, n in names.items():
            k = normalize(n)
            if k:
                self._ids.append(i)
                self._keys.append(k)

    def __len__(self) -> int:
        return len(self._keys)

    def match(self, text: str) -> tuple[str | None, float]:
        q = normalize(text)
        if len(q) < 2 or not self._keys:
            return None, 0.0
        hit = process.extractOne(q, self._keys, scorer=fuzz.ratio)
        if not hit:
            return None, 0.0
        key, score, pos = hit
        # 名字较长时允许 OCR 多识别出前后缀（如"棱彩阶"标记），用 partial 再试一次。
        if score < self.threshold and len(q) > 3:
            hit2 = process.extractOne(q, self._keys, scorer=fuzz.partial_ratio)
            if hit2 and hit2[1] >= 90 and len(hit2[0]) >= 3 and abs(len(hit2[0]) - len(q)) <= 3:
                key, score, pos = hit2
        if score < self.threshold:
            return None, float(score)
        return self._ids[pos], float(score)
