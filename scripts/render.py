"""
render.py — 关键词驱动的 3D 风格宣传片渲染器

用法：
    python render.py --keywords "主题|要点1|要点2|要点3" --out 成片.mp4
    python render.py --keywords "AI赋能高校学习|真实学习轨迹|前后测实证|可复用工作流" \
                     --style tech --out demo.mp4

设计哲学：
    关键词不是"喂给 AI 生成画面"，而是被解析成一堆确定性参数
    （配色、几何体、节奏、文案）。同样的关键词永远出同样的片子，
    能复现、能微调、不花钱——这就是"代码渲染"相对"AI 生成"的优势。
"""
import argparse
import math
import os
import random
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from geom3d import (cube, octahedron, icosahedron, point_sphere,
                    rotate, project, depth_sort)

# ---------- 路径与字体 ----------
HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
FONT_REG = "C:/Windows/Fonts/msyh.ttc"
FONT_BOLD = "C:/Windows/Fonts/msyhbd.ttc"
W, H = 1600, 900
FPS = 24


def font(size, bold=False):
    return ImageFont.truetype(FONT_BOLD if bold else FONT_REG, size)


def find_ffmpeg():
    """优先用 imageio-ffmpeg 自带的编码器，省得用户单独装 ffmpeg。"""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return "ffmpeg"


# ---------- 关键词 -> 视觉参数 ----------
# 这张表就是"AI 理解关键词"的全部——它其实是人为写的映射规则。
# 想让 skill 懂更多关键词，往表里加行即可，这就是你能改的地方。
STYLES = {
    "tech": {
        "bg": (10, 14, 24), "ink": (236, 242, 252), "accent": (94, 200, 255),
        "accent2": (124, 132, 255), "muted": (110, 126, 154),
        "shape": "icosahedron", "kicker": "TECH / INNOVATION",
    },
    "edu": {
        "bg": (14, 17, 26), "ink": (245, 238, 222), "accent": (240, 186, 92),
        "accent2": (228, 140, 88), "muted": (150, 142, 128),
        "shape": "octahedron", "kicker": "RESEARCH / PRACTICE",
    },
    "nature": {
        "bg": (9, 20, 19), "ink": (230, 245, 238), "accent": (92, 214, 168),
        "accent2": (128, 200, 224), "muted": (120, 152, 140),
        "shape": "icosahedron", "kicker": "GROWTH / SYSTEM",
    },
    "minimal": {
        "bg": (18, 18, 22), "ink": (244, 244, 246), "accent": (198, 196, 220),
        "accent2": (150, 150, 170), "muted": (130, 130, 140),
        "shape": "cube", "kicker": "FOCUS / ESSENCE",
    },
}

STYLE_HINTS = {
    "科技": "tech", "ai": "tech", "人工智能": "tech", "未来": "tech", "代码": "tech",
    "学习": "edu", "教育": "edu", "高校": "edu", "研究": "edu", "实证": "edu",
    "成长": "nature", "绿色": "nature", "生态": "nature", "自然": "nature",
    "极简": "minimal", "简约": "minimal", "设计": "minimal",
}


def parse_keywords(raw, style_hint=None):
    """把 '主题|要点1|要点2|要点3' 解析成结构化参数。"""
    parts = [p.strip() for p in raw.split("|") if p.strip()]
    title = parts[0] if parts else "未命名项目"
    points = parts[1:] or ["关键词一", "关键词二", "关键词三"]
    # 风格：显式指定 > 从关键词猜 > 默认 tech
    style = style_hint
    if not style:
        blob = raw.lower()
        for hint, st in STYLE_HINTS.items():
            if hint in blob:
                style = st
                break
    style = style or "tech"
    return {"title": title, "points": points[:3], "style": STYLES[style], "style_name": style}


# ---------- 绘图小工具 ----------
def seeded(shape_name):
    """固定随机种子：让粒子分布每次都一样，成片可复现。"""
    r = random.Random({"cube": 1, "octahedron": 2, "icosahedron": 3}[shape_name])
    return r


def tint(color, factor):
    return tuple(max(0, min(255, int(c * factor))) for c in color)


def mix(c1, c2, t):
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def ease(t):
    """缓动函数：让动画起步和收尾更柔和，不是匀速的机械感。"""
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def alpha_in_out(global_t, start, end, fade=0.5):
    """某段时间内的不透明度：淡入 -> 保持 -> 淡出。"""
    if global_t < start or global_t > end:
        return 0.0
    a = min(1.0, (global_t - start) / fade)
    b = min(1.0, (end - global_t) / fade)
    return max(0.0, min(a, b))


def draw_text(draw, xy, text, fnt, fill, anchor="la"):
    draw.text(xy, text, font=fnt, fill=fill, anchor=anchor,
              stroke_width=0)


# ---------- 核心：画一个 3D 物体 ----------
def draw_solid(draw, verts, faces, edges, t, cfg, cx, cy, palette, alpha=1.0,
               spin=1.0, scale=1.0, glow=False):
    """把 3D 几何体画到 2D 画布上。

    t 是时间（秒），驱动旋转角；alpha 控制淡入淡出。
    """
    ax = t * 0.42 * spin
    ay = t * 0.58 * spin + 0.4
    az = math.sin(t * 0.23) * 0.25
    rv = rotate(verts, ax, ay, az)
    xs, ys, depths = project(rv, cx, cy, focal=560, cam_z=6.5, scale=scale)

    # 面：按深度从远到近画，近的盖住远的
    for idx, shade in depth_sort(faces, depths):
        pts = [(xs[i], ys[i]) for i in idx]
        col = tint(palette, shade)
        if alpha < 1.0:
            col = mix(cfg["bg"], col, alpha)
        draw.polygon(pts, fill=col)

    # 边：高亮轮廓，让几何体在暗背景上更清晰
    edge_col = tint(palette, 1.25)
    if alpha < 1.0:
        edge_col = mix(cfg["bg"], edge_col, alpha)
    for a, b in edges:
        draw.line([(xs[a], ys[a]), (xs[b], ys[b])], fill=edge_col, width=2)

    if glow:
        # 顶点光点：在关键节点加个亮点，科技感来源之一
        for i in range(0, len(xs), max(1, len(xs) // 12)):
            r = 4
            draw.ellipse([xs[i]-r, ys[i]-r, xs[i]+r, ys[i]+r], fill=edge_col)


def draw_particles(draw, t, cfg, cx, cy, palette, alpha=1.0, n=90):
    """旋转的粒子球——用来做"数据/网络/连接"的背景意象。"""
    pts = point_sphere(n)
    rv = rotate(pts, t * 0.18, t * 0.25, 0)
    xs, ys, depths = project(rv, cx, cy, focal=600, cam_z=7.5, scale=1.9)
    order = np.argsort(-depths)  # 远的先画
    for i in order:
        z = depths[i]
        size = max(1.0, 5.0 * 7.0 / z)
        f = 0.35 + 0.65 * (7.5 - (z - 7.5)) / 15
        f = max(0.25, min(1.0, f))
        col = tint(palette, f)
        if alpha < 1.0:
            col = mix(cfg["bg"], col, alpha)
        draw.ellipse([xs[i]-size, ys[i]-size, xs[i]+size, ys[i]+size], fill=col)


def draw_grid(draw, t, cfg, alpha=0.5):
    """透视网格地面——给画面一个"空间感"的锚点。"""
    col = mix(cfg["bg"], cfg["muted"], 0.22 * alpha)
    horizon = int(H * 0.68)
    for i in range(1, 16):
        y = horizon + (i ** 1.9) * 2.2
        if y > H:
            break
        draw.line([(0, y), (W, y)], fill=col, width=1)
    offset = (t * 26) % 80
    for x in range(-80, W + 80, 80):
        draw.line([(x + offset, horizon), (W//2 + (x + offset - W//2) * 3.2, H)],
                  fill=col, width=1)


# ---------- 分镜：把整条片子切成几幕 ----------
def scene_at(t, total):
    """根据时间返回当前幕。节奏：片头 -> 3 要点 -> 收尾。"""
    intro = 4.0
    outro = 4.0
    if t < intro:
        return "intro", t / intro
    body = total - intro - outro
    if t < intro + body:
        local = t - intro
        idx = min(2, int(local / (body / 3)))
        seg = body / 3
        return f"point{idx}", (local - idx * seg) / seg
    return "outro", (t - intro - body) / outro


def render_frame(frame_idx, params, total_frames):
    """渲染单帧——整个 skill 的心脏。所有画面都是这个函数一帧帧画出来的。"""
    t = frame_idx / FPS
    total = total_frames / FPS
    cfg = params["style"]
    img = Image.new("RGB", (W, H), cfg["bg"])
    d = ImageDraw.Draw(img, "RGBA")

    scene, progress = scene_at(t, total)
    accent = cfg["accent"]
    accent2 = cfg["accent2"]
    ink = cfg["ink"]

    # 背景空间网格（所有幕共用）
    draw_grid(d, t, cfg, alpha=0.8)

    # 预建几何体（一次建好，每帧只是旋转，省性能）
    shape_name = cfg["shape"]
    if shape_name == "cube":
        verts, faces, edges = cube(1.5)
    elif shape_name == "octahedron":
        verts, faces, edges = octahedron(1.9)
    else:
        verts, faces, edges = icosahedron(1.7)

    if scene == "intro":
        a = alpha_in_out(t, 0, 4.0, fade=0.7)
        draw_particles(d, t, cfg, W//2, H//2 - 20, mix(accent, accent2, 0.3), a * 0.7, 70)
        draw_solid(d, verts, faces, edges, t, cfg, W//2, H//2 - 20, accent,
                   alpha=a, spin=1.15, scale=1.25, glow=True)
        k = ease(progress)
        draw_text(d, (150, 150), cfg["kicker"], font(22), (*cfg["muted"], int(255*a)))
        title = params["title"]
        title_f = font(66, True)
        draw_text(d, (150, 250 + int((1-k)*22)), title, title_f,
                  (*ink, int(255*a)))
        draw_text(d, (152, 350), "关键词驱动的 3D 动画 · 本地渲染 无需 AI 生成接口",
                  font(24), (*accent, int(255*a)))
        # 进度线
        d.rounded_rectangle([150, 430, 150 + int(420*k), 435], radius=2,
                            fill=(*accent, int(255*a)))

    elif scene.startswith("point"):
        idx = int(scene[-1])
        pt = params["points"][idx] if idx < len(params["points"]) else "要点"
        a = alpha_in_out(t, scene_at(t, total)[1] * 0 + (4.0 + idx*(total-8)/3),
                         4.0 + (idx+1)*(total-8)/3, fade=0.6)
        # 主体几何体偏右，文字偏左，形成阅读动线
        draw_particles(d, t, cfg, int(W*0.70), H//2, accent2, a * 0.55, 80)
        draw_solid(d, verts, faces, edges, t + idx*1.3, cfg,
                   int(W*0.70), H//2, accent, alpha=a, spin=1.0,
                   scale=1.15, glow=True)
        draw_text(d, (150, 165), f"0{idx+1} / 0{len(params['points'])}",
                  font(22, True), (*accent, int(255*a)))
        draw_text(d, (150, 300), pt, font(58, True), (*ink, int(255*a)))
        draw_text(d, (152, 400), "由关键词解析生成 · 可编辑可复现",
                  font(24), (*cfg["muted"], int(255*a)))
        # 装饰短线
        for j in range(3):
            yy = 470 + j * 34
            d.rounded_rectangle([150, yy, 150 + int((260 - j*60) * ease(min(1, progress*1.5))), yy+3],
                                radius=1, fill=(*accent2, int(200*a)))

    else:  # outro
        a = alpha_in_out(t, total - 4.0, total, fade=0.8)
        k = ease(progress)
        draw_particles(d, t, cfg, W//2, H//2, accent, a * 0.8, 90)
        draw_solid(d, verts, faces, edges, t, cfg, W//2, H//2 - 30,
                   mix(accent, accent2, 0.5), alpha=a, spin=0.8,
                   scale=0.9 + k*0.3, glow=True)
        draw_text(d, (W//2, H - 190), "稳稳做完，就是胜利", font(48, True),
                  (*ink, int(255*a)), anchor="ma")
        draw_text(d, (W//2, H - 120), "keyword-3d-video · 关键词驱动 3D 动画",
                  font(22), (*accent, int(255*a)), anchor="ma")

    # 统一的底部信息条
    d.line([(150, H-70), (W-150, H-70)], fill=(*cfg["muted"], 120), width=1)
    draw_text(d, (150, H-56), "LOCAL RENDER · DETERMINISTIC · NO API COST",
              font(16), (*cfg["muted"], 180))
    draw_text(d, (W-150, H-56), f"{frame_idx+1:04d}/{total_frames:04d}",
              font(16), (*cfg["muted"], 180), anchor="ra")
    return img


def render_video(keywords, out_path, style_hint=None, duration=24.0):
    params = parse_keywords(keywords, style_hint)
    total_frames = int(duration * FPS)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)

    # 逐帧渲染，直接把 RGB 字节流管道给 ffmpeg，不落盘、不占空间
    ff = find_ffmpeg()
    cmd = [ff, "-y", "-f", "rawvideo", "-vcodec", "rawvideo",
           "-s", f"{W}x{H}", "-pix_fmt", "rgb24", "-r", str(FPS),
           "-i", "-", "-an", "-c:v", "libx264", "-preset", "medium",
           "-crf", "20", "-pix_fmt", "yuv420p", out_path]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        for i in range(total_frames):
            img = render_frame(i, params, total_frames)
            proc.stdin.write(img.tobytes())
            if i % (FPS * 4) == 0:
                print(f"rendered {i}/{total_frames} frames", flush=True)
        proc.stdin.close()
        err = proc.stderr.read().decode("utf-8", "ignore")
        code = proc.wait()
        if code != 0:
            raise RuntimeError(f"ffmpeg failed ({code}): {err[-800:]}")
    except Exception:
        proc.kill()
        raise
    print(f"DONE: {out_path}")
    return out_path


def main():
    ap = argparse.ArgumentParser(description="关键词驱动的 3D 风格宣传片渲染器")
    ap.add_argument("--keywords", required=True,
                    help="用 | 分隔：主题|要点1|要点2|要点3")
    ap.add_argument("--out", required=True, help="输出 MP4 路径")
    ap.add_argument("--style", default=None,
                    help="风格：tech/edu/nature/minimal（不填则从关键词猜）")
    ap.add_argument("--duration", type=float, default=24.0, help="时长秒数")
    args = ap.parse_args()
    render_video(args.keywords, args.out, args.style, args.duration)


if __name__ == "__main__":
    main()
