"""把「海克斯反差榜.html」按段落转成分享图片（images/1-…png ~ 5-…png）。

用法：
  python -m pip install playwright          # 不用下载浏览器，直接用本机 Edge
  python docs/hex-contrast/to_images.py
"""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
WIDTH = 720  # 手机阅读宽度（CSS 像素）；按 2 倍导出，图片实际宽 1440
NAMES = ["1-科学狂人", "2-逃跑计划", "3-全能龙魂", "4-虚幻武器", "5-英雄神组合"]  # 与页面里 <section> 顺序一一对应

# 截图专用样式：隐藏原页面，每个 <section> 包成一张独立卡片
CSS = """<style>
body{padding:0!important;margin:0}
.wrap{display:none}
.card{width:%dpx;box-sizing:border-box;background:var(--bg);padding:36px 32px 26px;display:flex;flex-direction:column;gap:18px}
.card .strip{display:flex;justify-content:space-between;font-size:12.5px;letter-spacing:.1em;color:var(--muted);border-bottom:1px solid var(--line);padding-bottom:10px}
.card .strip b{color:var(--prism);letter-spacing:.06em}
.card .fn{font-size:12px;color:var(--muted);border-top:1px solid var(--line);padding-top:10px;line-height:1.5}
</style>""" % WIDTH

# 分页规则：一个 <section> 一张图，不在段落中间切开。
# 每张：顶部"海克斯大乱斗 · 国服 16.19"和页码；第 1 张额外带页面大标题和"怎么读"；
# 底部带"收益"的定义和版本日期（最后一张改用页面原来的页脚），单独转发也看得懂。
JS = r"""
() => {
  const w = document.querySelector('.wrap');
  const header = w.querySelector('header');
  const secs = [...w.querySelectorAll('section')];
  const foot = w.querySelector('footer');
  const total = secs.length;
  const fn = '收益 = 拿了这张海克斯的对局胜率 − 该英雄平均胜率（百分点），每个英雄只统计 ≥3000 场的海克斯。国服版本 16.19，2026-09-28 整理。';
  secs.forEach((s, i) => {
    const c = document.createElement('div'); c.className = 'card'; c.id = 'card' + (i + 1);
    const strip = document.createElement('div'); strip.className = 'strip';
    strip.innerHTML = `<span>海克斯大乱斗 · 国服 16.19</span><b>${i + 1} / ${total}</b>`;
    c.appendChild(strip);
    if (i === 0) { const h = header.cloneNode(true); h.querySelector('.eyebrow').remove(); c.appendChild(h); }
    c.appendChild(s.cloneNode(true));
    const f = document.createElement('div'); f.className = 'fn';
    f.textContent = (i === total - 1) ? foot.innerText.split('\n').filter(Boolean).join(' ') : fn;
    c.appendChild(f);
    document.body.appendChild(c);
  });
  return total;
}
"""


def main():
    src = (HERE / "海克斯反差榜.html").read_text(encoding="utf-8")
    out = HERE / "images"
    out.mkdir(exist_ok=True)
    doc = "<!doctype html><html><head><meta charset='utf-8'></head><body>" + src + CSS + "</body></html>"
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")  # 没有 Edge 可改 channel="chrome"
        page = browser.new_page(viewport={"width": WIDTH, "height": 1000}, device_scale_factor=2, color_scheme="light")
        page.set_content(doc, wait_until="networkidle")  # 等 Google Fonts 加载完
        page.evaluate("document.fonts.ready")
        n = page.evaluate(JS)
        page.wait_for_timeout(500)
        for i in range(n):
            name = NAMES[i] if i < len(NAMES) else f"{i + 1}"
            page.locator(f"#card{i + 1}").screenshot(path=str(out / f"{name}.png"))
            print(out / f"{name}.png")
        browser.close()


if __name__ == "__main__":
    main()
