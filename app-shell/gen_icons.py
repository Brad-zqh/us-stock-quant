"""生成 PWA / App 图标 (纯标准库, 无需 Pillow)。
深色背景 + 绿色上升折线 + 红色蜡烛感, 简洁可辨识。可自行替换成品牌图。
"""
import struct, zlib, os

OUT = os.path.join(os.path.dirname(__file__), "web", "icons")
os.makedirs(OUT, exist_ok=True)


def _png(path, pixels, w, h):
    raw = bytearray()
    for y in range(h):
        raw.append(0)  # filter type 0
        row = pixels[y * w * 4:(y + 1) * w * 4]
        raw.extend(row)
    comp = zlib.compress(bytes(raw), 9)

    def chunk(typ, data):
        c = struct.pack(">I", len(data)) + typ + data
        c += struct.pack(">I", zlib.crc32(typ + data) & 0xffffffff)
        return c

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)  # 8-bit RGBA
    with open(path, "wb") as f:
        f.write(sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", comp) + chunk(b"IEND", b""))


def make(size, maskable=False):
    w = h = size
    px = bytearray(w * h * 4)
    bg = (14, 17, 23)          # #0e1117
    panel = (22, 27, 34)       # 圆角面板
    green = (38, 166, 154)     # 上升线
    red = (239, 83, 80)        # 蜡烛红
    yellow = (244, 211, 94)

    # 圆角矩形面板 (maskable 时留出安全边距, 铺满背景)
    margin = 0 if maskable else int(size * 0.09)
    radius = int(size * 0.22)

    def in_panel(x, y):
        if x < margin or y < margin or x >= w - margin or y >= h - margin:
            return False
        # 圆角
        rx0, ry0 = margin + radius, margin + radius
        rx1, ry1 = w - margin - radius, h - margin - radius
        cx = min(max(x, rx0), rx1)
        cy = min(max(y, ry0), ry1)
        return (x - cx) ** 2 + (y - cy) ** 2 <= radius ** 2 or (
            rx0 <= x <= rx1 or ry0 <= y <= ry1)

    def setpx(x, y, c):
        if 0 <= x < w and 0 <= y < h:
            i = (y * w + x) * 4
            px[i], px[i+1], px[i+2], px[i+3] = c[0], c[1], c[2], 255

    for y in range(h):
        for x in range(w):
            if maskable:
                setpx(x, y, panel if in_panel(x, y) else bg)
            else:
                setpx(x, y, panel if in_panel(x, y) else bg)
                if x < margin or y < margin or x >= w - margin or y >= h - margin:
                    setpx(x, y, bg)

    # 画一条上升折线 (代表趋势/涨)
    pts = [(0.18, 0.72), (0.34, 0.58), (0.5, 0.64), (0.66, 0.40), (0.82, 0.26)]
    line_w = max(2, int(size * 0.035))

    def line(p0, p1, color):
        x0, y0 = int(p0[0]*size), int(p0[1]*size)
        x1, y1 = int(p1[0]*size), int(p1[1]*size)
        steps = max(abs(x1-x0), abs(y1-y0), 1)
        for s in range(steps+1):
            x = x0 + (x1-x0)*s//steps
            y = y0 + (y1-y0)*s//steps
            for dx in range(-line_w, line_w+1):
                for dy in range(-line_w, line_w+1):
                    if dx*dx+dy*dy <= line_w*line_w:
                        setpx(x+dx, y+dy, color)

    for i in range(len(pts)-1):
        line(pts[i], pts[i+1], green)
    # 端点小圆点
    for (fx, fy) in [pts[-1]]:
        cx, cy = int(fx*size), int(fy*size)
        r = int(size*0.05)
        for dx in range(-r, r+1):
            for dy in range(-r, r+1):
                if dx*dx+dy*dy <= r*r:
                    setpx(cx+dx, cy+dy, yellow)

    # 两根小蜡烛柱 (点缀)
    for (fx, top, bot) in [(0.28, 0.50, 0.78), (0.60, 0.36, 0.62)]:
        cx = int(fx*size)
        bw = max(2, int(size*0.045))
        for x in range(cx-bw, cx+bw):
            for y in range(int(top*size), int(bot*size)):
                setpx(x, y, red)

    _png(os.path.join(OUT, f"icon-{size}.png") if not maskable
         else os.path.join(OUT, "icon-maskable-512.png"), px, w, h)


make(192)
make(512)
make(512, maskable=True)
print("icons written to", OUT)
