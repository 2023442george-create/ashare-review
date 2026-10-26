"""生成桌面快捷方式用的 app.ico（纯标准库，不依赖 Pillow）。

画一个深色圆角方块 + 红色上升箭头（A 股涨=红）。先按 4 倍超采样渲染再降采样，
避免纯像素画出来的斜线出现锯齿。

用法：python scripts/make_icon.py [输出路径]
"""
from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

SIZE = 64
SS = 4  # 超采样倍数
BIG = SIZE * SS

BG = (15, 23, 42, 255)        # #0F172A
BORDER = (30, 41, 59, 255)    # #1E293B
RED = (239, 68, 68, 255)      # #EF4444
RED_DARK = (220, 38, 38, 255)  # #DC2626


def _rounded_rect(x: float, y: float, w: float, h: float, r: float) -> bool:
    if x < 0 or y < 0 or x > w or y > h:
        return False
    cx = min(max(x, r), w - r)
    cy = min(max(y, r), h - r)
    dx, dy = x - cx, y - cy
    return dx * dx + dy * dy <= r * r


def _in_thick_segment(px, py, x1, y1, x2, y2, half) -> bool:
    """点到线段距离 <= half。"""
    vx, vy = x2 - x1, y2 - y1
    wx, wy = px - x1, py - y1
    seg = vx * vx + vy * vy
    t = 0.0 if seg == 0 else max(0.0, min(1.0, (wx * vx + wy * vy) / seg))
    dx, dy = px - (x1 + t * vx), py - (y1 + t * vy)
    return dx * dx + dy * dy <= half * half


def _in_triangle(px, py, a, b, c) -> bool:
    def sign(p1, p2, p3):
        return (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])

    d1, d2, d3 = sign((px, py), a, b), sign((px, py), b, c), sign((px, py), c, a)
    neg = d1 < 0 or d2 < 0 or d3 < 0
    pos = d1 > 0 or d2 > 0 or d3 > 0
    return not (neg and pos)


def render_big() -> bytearray:
    buf = bytearray(BIG * BIG * 4)  # 全透明

    margin = 2 * SS
    radius = 14 * SS
    w = h = BIG - margin * 2

    # 圆角底板（外描边 + 内填充）
    for y in range(BIG):
        for x in range(BIG):
            if _rounded_rect(x - margin, y - margin, w, h, radius):
                i = (y * BIG + x) * 4
                inner = _rounded_rect(x - margin - SS, y - margin - SS,
                                      w - 2 * SS, h - 2 * SS, max(1.0, radius - SS))
                color = BG if inner else BORDER
                buf[i:i + 4] = bytes(color)

    # 上升箭头：从 (18,46) 到 (44,18)，箭头头部三角
    x1, y1 = 18 * SS, 46 * SS
    x2, y2 = 43 * SS, 19 * SS
    half = 4.0 * SS
    tip = (47 * SS, 14 * SS)
    left = (36 * SS, 17 * SS)
    right = (44 * SS, 26 * SS)

    for y in range(BIG):
        for x in range(BIG):
            if _in_thick_segment(x, y, x1, y1, x2, y2, half) or _in_triangle(x, y, tip, left, right):
                i = (y * BIG + x) * 4
                if buf[i + 3] == 0:
                    continue
                buf[i:i + 4] = bytes(RED)

    # 底部两根柱子，暗示 K 线
    for bx, top in ((14 * SS, 40 * SS), (22 * SS, 34 * SS)):
        for y in range(top, 50 * SS):
            for x in range(bx, bx + 3 * SS):
                i = (y * BIG + x) * 4
                if buf[i + 3] == 0:
                    continue
                buf[i:i + 4] = bytes(RED_DARK)

    return buf


def downsample(big: bytearray) -> bytes:
    out = bytearray()
    for y in range(SIZE):
        out.append(0)  # PNG filter: none
        for x in range(SIZE):
            r = g = b = a = 0
            for dy in range(SS):
                for dx in range(SS):
                    i = (((y * SS + dy) * BIG) + (x * SS + dx)) * 4
                    r += big[i]; g += big[i + 1]; b += big[i + 2]; a += big[i + 3]
            n = SS * SS
            out += bytes((r // n, g // n, b // n, a // n))
    return bytes(out)


def png(raw: bytes) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def ico(png_bytes: bytes) -> bytes:
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", SIZE, SIZE, 0, 0, 1, 32,
                        len(png_bytes), 6 + 16)
    return header + entry + png_bytes


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "assets" / "app.ico"
    out.parent.mkdir(parents=True, exist_ok=True)
    data = ico(png(downsample(render_big())))
    out.write_bytes(data)
    print(f"written: {out} ({len(data)} bytes)")


if __name__ == "__main__":
    main()
