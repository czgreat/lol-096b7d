"""生成程序图标：深色底的金色六边形（海克斯）+ 内部三张卡片意象。
输出 packaging/lolhex.ico（多尺寸）与 lolhex/ui/icon.png（256px，给 Qt 用）。"""

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent


def hexagon(cx, cy, r, rot=math.pi / 6):
    return [(cx + r * math.cos(rot + i * math.pi / 3), cy + r * math.sin(rot + i * math.pi / 3)) for i in range(6)]


def render(size: int = 1024) -> Image.Image:
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = s / 2
    # 外发光
    glow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(glow).polygon(hexagon(c, c, s * 0.47), fill=(231, 195, 90, 150))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(s * 0.03)))
    # 深色六边形底 + 金边
    d.polygon(hexagon(c, c, s * 0.46), fill=(231, 195, 90, 255))
    d.polygon(hexagon(c, c, s * 0.415), fill=(18, 24, 38, 255))
    d.polygon(hexagon(c, c, s * 0.37), outline=(98, 168, 255, 255), width=max(2, s // 64))
    # 中间三张竖卡（三选一），中间那张高亮为金色
    w, h, gap = s * 0.13, s * 0.30, s * 0.035
    xs = [c - w * 1.5 - gap, c - w / 2, c + w / 2 + gap]
    for i, x in enumerate(xs):
        y = c - h / 2 + (0 if i == 1 else s * 0.03)
        hh = h if i == 1 else h * 0.82
        col = (231, 195, 90, 255) if i == 1 else (98, 168, 255, 230)
        d.rounded_rectangle([x, y, x + w, y + hh], radius=s * 0.02, fill=col)
        d.rounded_rectangle([x + s * 0.02, y + s * 0.02, x + w - s * 0.02, y + hh * 0.45], radius=s * 0.012,
                            fill=(18, 24, 38, 255))
    # 顶部小菱形（海克斯核心）
    d.polygon([(c, c - s * 0.30), (c + s * 0.035, c - s * 0.255), (c, c - s * 0.21), (c - s * 0.035, c - s * 0.255)],
              fill=(255, 236, 170, 255))
    return img


def main():
    big = render(1024)
    sizes = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]
    ico = ROOT / "packaging" / "lolhex.ico"
    big.save(ico, sizes=[(n, n) for n in sizes])
    png = ROOT / "lolhex" / "ui" / "icon.png"
    big.resize((256, 256), Image.LANCZOS).save(png)
    print("written", ico, png)


if __name__ == "__main__":
    main()
