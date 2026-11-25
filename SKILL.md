---
name: keyword-3d-video
description: 用关键词生成 3D 动画风格的宣传片/短片 MP4。当用户说"用关键词做个3D视频""做个科技感动画短片""3D风格宣传片""关键词驱动的视频"等需求时使用。本地代码渲染，免费、可复现、字幕精确可控；不调用云端 AI 视频接口，做不了写实人物/动物动画。
agent_created: true
---

# Keyword 3D Video

把关键词变成一条 3D 动画风格的 MP4。**关键词不是喂给 AI 生成画面，而是被解析成确定性参数**（配色、几何体、节奏、文案），所以同样的输入永远出同样的片子——免费、能复现、字幕排版精确。

## 什么时候用

- 用户要"科技感 / 3D 风格"的片头、宣传片、概念短片
- 用户有主题 + 几个要点，想快速出一条能播的视频
- 用户明确说不想花钱调 AI 视频接口

## 什么时候不用（诚实边界）

- 要写实的人物、动物、具体场景动画 → 那是云端视频大模型（可灵/即梦/Sora）的活，本 skill 做不了
- 要剪用户自己拍的素材 → 用剪映或 video-shotcraft，不是本 skill
- 要精确到每个镜头的复杂叙事 → 本 skill 是模板化分镜，框架内可调

## 怎么用

调用 `scripts/render.py`：

```bash
python scripts/render.py \
  --keywords "主题|要点1|要点2|要点3" \
  --style tech \
  --duration 24 \
  --out "输出路径.mp4"
```

参数：
- `--keywords`：用 `|` 分隔，第一段是标题，后面是要点（最多取 3 段）
- `--style`：`tech` / `edu` / `nature` / `minimal`；不填则根据关键词自动猜
- `--duration`：秒数，默认 24
- `--out`：输出 MP4 路径

## 输出规格

1600×900，24 fps，H.264 yuv420p，无音轨。逐帧直接管道给 ffmpeg，不落中间图片。24 秒约 576 帧，普通机器几十秒到两三分钟。

## 实现原理（教学）

两个文件，各管一层：

1. **`scripts/geom3d.py`** — 3D 数学地基
   - `rotate()`：旋转矩阵，绕三个轴转点
   - `project()`：透视投影，`screen = center + point * focal / (z + cam_z)`，分母的 z 造成近大远小
   - `depth_sort()`：画家算法，远的先画、近的后画，实现遮挡
   - 内置四种几何体：立方体、八面体、二十面体、粒子球

2. **`scripts/render.py`** — 分镜与渲染
   - `parse_keywords()`：关键词 → 视觉参数（这里就是"AI 理解关键词"的全部，是一张人为写的映射表）
   - `render_frame()`：画单帧。分四幕：片头 → 三个要点 → 收尾
   - `render_video()`：逐帧生成 RGB 字节流，管道喂给 ffmpeg 编码

## 怎么改（用户可自助）

| 想改什么 | 改哪里 |
|---|---|
| 配色 / 风格 | `render.py` 里的 `STYLES` 字典，加一套新风格 |
| 关键词识别规则 | `render.py` 里的 `STYLE_HINTS` 字典，加关键词映射 |
| 换几何体 | `geom3d.py` 加新函数，或改 `STYLES[*]["shape"]` |
| 分镜节奏 | `render.py` 的 `scene_at()` 改每幕时长 |
| 字幕文案 / 排版 | `render_frame()` 里的 `draw_text` 调用 |
| 分辨率 / 帧率 | `render.py` 顶部的 `W, H, FPS` |

## 依赖

Python 环境需装 `pillow numpy imageio-ffmpeg`（本机已装在 managed venv）。
中文字体用系统微软雅黑 `C:/Windows/Fonts/msyh.ttc` / `msyhbd.ttc`。
