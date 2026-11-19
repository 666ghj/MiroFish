"""
MiroFish 图标生成器

不依赖任何三方库（只用 Python 标准库 zlib），把同一份绘制指令分别输出为：
  - PNG（用于窗口图标 / pywebview，代码里直接内嵌为 base64 字符串）
  - ICO（多尺寸，用于 Windows 可执行文件）

图形：深蓝底 + 青色鱼形（MiroFish 的极简标识）。
"""

import struct
import zlib

BG = (9, 20, 38)
BG2 = (16, 42, 74)
FISH = (255, 255, 255)
FISH_DARK = (34, 211, 238)
ACCENT = (56, 189, 248)


def _lerp(a, b, t):
    return a + (b - a) * t


def _blend(dst, src, alpha):
    return tuple(int(round(_lerp(d, s, alpha))) for d, s in zip(dst, src))


def _rounded_mask(x, y, size, radius):
    """点 (x,y) 是否在圆角矩形内。"""
    r = radius
    cx = min(max(x, r), size - r)
    cy = min(max(y, r), size - r)
    dx, dy = x - cx, y - cy
    return dx * dx + dy * dy <= r * r


def _fish_alpha(x, y, size):
    """返回鱼形在该点的覆盖率（0~1），用超采样调用。"""
    s = size
    u = (x - s / 2) / (s / 2)   # -1 .. 1
    v = (y - s / 2) / (s / 2)

    # 身体：椭圆
    body = (u / 0.74) ** 2 + (v / 0.40) ** 2 <= 1.0

    # 尾巴：右端三角形（鱼头朝左）
    tail = False
    if 0.42 <= u <= 0.92:
        half = 0.42 * (u - 0.42) / 0.50
        tail = abs(v) <= half

    if body or tail:
        return 1.0

    # 背鳍：贴在身体上方的三角形
    if -0.16 <= u <= 0.36 and v < 0:
        # 三角形的三条边：底边在 v=-0.33，顶点在 (0.02, -0.76)
        top = -0.33 - 0.43 * (1.0 - abs(u - 0.02) / 0.34)
        if v <= -0.33 and v >= top:
            return 1.0

    return 0.0


def _pixel_color(x, y, size, ss=3):
    """在 (x, y) 处做 ss×ss 超采样，返回 RGBA。"""
    cover = 0.0
    fish = 0.0
    total = ss * ss
    for i in range(ss):
        for j in range(ss):
            px = x + (i + 0.5) / ss
            py = y + (j + 0.5) / ss
            if not _rounded_mask(px, py, size, size * 0.22):
                continue
            cover += 1.0
            fish += _fish_alpha(px, py, size)

    if cover == 0:
        return (0, 0, 0, 0)

    a = cover / total
    # 背景：对角渐变
    t = (x + y) / (2.0 * size)
    bg = tuple(int(round(_lerp(c1, c2, t))) for c1, c2 in zip(BG, BG2))

    fish_ratio = fish / total
    if fish_ratio > 0:
        # 鱼身留白 + 左侧眼睛
        c = FISH
        ex = x - size * 0.30
        ey = y - size * 0.47
        if ex * ex + ey * ey <= (size * 0.055) ** 2:
            c = ACCENT
        bg = _blend(bg, c, min(1.0, fish_ratio * 1.15))

    return (bg[0], bg[1], bg[2], int(round(a * 255)))


def render_rgba(size):
    rows = []
    for y in range(size):
        row = bytearray()
        for x in range(size):
            row.extend(_pixel_color(x, y, size))
        rows.append(bytes(row))
    return rows


def _png_chunk(tag, data):
    chunk = struct.pack('>I', len(data)) + tag + data
    return chunk + struct.pack('>I', zlib.crc32(tag + data) & 0xFFFFFFFF)


def png_bytes(size):
    rows = render_rgba(size)
    raw = b''.join(b'\x00' + r for r in rows)
    ihdr = struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0)
    return (b'\x89PNG\r\n\x1a\n'
            + _png_chunk(b'IHDR', ihdr)
            + _png_chunk(b'IDAT', zlib.compress(raw, 9))
            + _png_chunk(b'IEND', b''))


def ico_bytes(sizes=(16, 24, 32, 48, 64, 128, 256)):
    """生成多尺寸 ICO（内部使用 PNG 压缩，Vista+ 支持）。"""
    images = [png_bytes(s) for s in sizes]
    header = struct.pack('<HHH', 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b'', b''
    for s, data in zip(sizes, images):
        entries += struct.pack('<BBBBHHII', s if s < 256 else 0, s if s < 256 else 0,
                               0, 0, 1, 32, len(data), offset)
        blobs += data
        offset += len(data)
    return header + entries + blobs


if __name__ == '__main__':
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else 'icon'
    with open(out + '.ico', 'wb') as f:
        f.write(ico_bytes())
    with open(out + '.png', 'wb') as f:
        f.write(png_bytes(256))
    print('wrote', out + '.ico', out + '.png')
