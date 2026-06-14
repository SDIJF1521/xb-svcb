"""把源图标 PNG 生成 Windows 多尺寸 .ico（及一张 256 PNG）。

用法：
    python installer/make_icon.py [源png] [输出ico]
默认：assets/icon/source.png -> assets/icon/xb-svcb.ico
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "assets" / "icon" / "source.png"
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "assets" / "icon" / "xb-svcb.ico"

SIZES = [16, 24, 32, 48, 64, 128, 256]


def squarify(im: Image.Image) -> Image.Image:
    """按内容透明边界裁剪后，居中补成正方形（透明背景）。"""
    im = im.convert("RGBA")
    bbox = im.getbbox()
    if bbox:
        im = im.crop(bbox)
    w, h = im.size
    side = max(w, h)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(im, ((side - w) // 2, (side - h) // 2), im)
    return canvas


def main() -> None:
    src = Image.open(SRC)
    sq = squarify(src)
    # 高质量放大到 256 作为基准
    base = sq.resize((256, 256), Image.LANCZOS)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    base.save(OUT, format="ICO", sizes=[(s, s) for s in SIZES])
    base.save(OUT.with_suffix(".png"))
    print(f"icon written: {OUT}  ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
