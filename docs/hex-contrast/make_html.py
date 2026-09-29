"""用内置数据（bundled-data/hexdata.json）生成「海克斯反差榜」网页：template.html → 海克斯反差榜.html。

用法（仓库根目录）：python docs/hex-contrast/make_html.py
换了新的 hexdata.json 后重跑即可；页面里的文字结论（"全部海克斯第一"等）要人工核对是否仍成立。
"""

from __future__ import annotations

import html
import json
import statistics as st
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from lolhex.data import hexdata  # noqa: E402

MIN_GAMES = 3000  # 每个英雄只统计 ≥3000 场的海克斯
SCIENTIST, ESCAPE, DRAGONS, VEIL = "1053", "1333", "1062", "1029"  # 科学狂人、逃跑计划、全能龙魂、虚幻武器
# 单英雄神组合：(海克斯, 英雄, 说明)。收益和胜率从数据里取
COMBOS = [("1134", "沙漠玫瑰", "远程变近战，失去的射程换成属性"), ("1134", "皮城女警", "射程越长，换得越多"),
          ("1058", "不灭狂雷", "整体是 −3.6 的烂牌，只在他手里是神牌"), ("2062", "卡牌大师", "24 万场，样本极大"),
          ("1015", "祖安狂人", "治疗量转成伤害"), ("1134", "法外狂徒", "39 万场")]


def rows(parsed, heroes, aid):
    """该海克斯在每个英雄上的收益（百分点）、胜率、场次，以及在该英雄所有海克斯里的名次。"""
    out = []
    for hid, p in parsed.items():
        base, x = p["sample_win"], p["augments"].get(aid)
        if not x or x["games"] < MIN_GAMES:
            continue
        ranked = sorted((k for k, v in p["augments"].items() if v["games"] >= MIN_GAMES),
                        key=lambda k: -(p["augments"][k]["win"] - base))
        out.append(dict(n=heroes[hid]["name"], g=(x["win"] - base) * 100, w=x["win"] * 100,
                        games=x["games"], rk=ranked.index(aid) + 1, of=len(ranked)))
    return sorted(out, key=lambda r: -r["g"])


def games(n):
    return f"{n / 10000:.1f} 万" if n >= 10000 else f"{n} "


def bars(rs, scale):
    items = []
    for r in rs:
        pct = max(0, min(100, r["g"] / scale * 100))
        items.append(f'<li><span class="hero">{html.escape(r["n"])}</span><span class="track"><span class="bar" '
                     f'style="width:{pct:.1f}%"></span></span><span class="num">+{r["g"]:.1f}</span><span class="meta">'
                     f'胜率 {r["w"]:.1f}% · {games(r["games"])}场 · <span class="rk">第 {r["rk"]} / {r["of"]}</span></span></li>')
    return "<ol class='bars'>" + "".join(items) + "</ol>"


def diverging(rs, scale):
    items = []
    for r in rs:
        pct = min(50, abs(r["g"]) / scale * 50)
        cls, style = ("pos", f"left:50%;width:{pct:.1f}%") if r["g"] > 0 else ("neg", f"right:50%;width:{pct:.1f}%")
        items.append(f'<li class="{cls}"><span class="hero">{html.escape(r["n"])}</span><span class="track dv">'
                     f'<span class="axis"></span><span class="bar" style="{style}"></span></span>'
                     f'<span class="num">{r["g"]:+.1f}</span><span class="meta">{games(r["games"])}场</span></li>')
    return "<ol class='bars'>" + "".join(items) + "</ol>"


def main():
    raw = json.loads((ROOT / "bundled-data" / "hexdata.json").read_text(encoding="utf-8"))
    parsed, heroes = hexdata.parse(raw), raw["heroes"]
    by_name = {h["name"]: hid for hid, h in heroes.items()}
    names = {a["augment_id"]: a.get("augment_name") for h in heroes.values() for a in h["augments"]}
    sci, esc, dra, veil = (rows(parsed, heroes, a) for a in (SCIENTIST, ESCAPE, DRAGONS, VEIL))

    cards = []
    for aid, hero, note in COMBOS:
        p = parsed[by_name[hero]]
        x = p["augments"][aid]
        cards.append(f'<li><div class="cg">+{(x["win"] - p["sample_win"]) * 100:.1f}</div><div><b>{names[aid]}</b> × {hero}'
                     f'<div class="cm">拿了后胜率 {x["win"] * 100:.1f}% · {html.escape(note)}</div></div></li>')

    rep = {"@sci": bars(sci[:10], 9), "@esc": bars(esc[:10], 6), "@dra": bars(dra[:10], 6),
           "@vw": diverging(veil[:7] + veil[-4:], 10), "@cmb": "".join(cards),
           "@scilow": "、".join(f"{r['n']}（{r['g']:+.1f}）" for r in sci[-3:]),
           "@dralow": "、".join(f"{r['n']}（{r['g']:+.1f}）" for r in dra[-4:])}
    for key, rs in (("S1", sci), ("S2", esc), ("S3", dra), ("S4", veil)):
        g = [r["g"] for r in rs]
        rep.update({f"@{key}pos": str(sum(v > 0 for v in g)), f"@{key}n": str(len(rs)),
                    f"@{key}t10": str(sum(r["rk"] <= 10 for r in rs)), f"@{key}med": f"{st.median(g):.1f}"})
    page = (HERE / "template.html").read_text(encoding="utf-8")
    for k in sorted(rep, key=len, reverse=True):  # 长的先换，避免 @sci 把 @scilow 的前半截换掉
        page = page.replace(k, rep[k])
    (HERE / "海克斯反差榜.html").write_text(page, encoding="utf-8", newline="\n")
    print("已生成", HERE / "海克斯反差榜.html")


if __name__ == "__main__":
    main()
