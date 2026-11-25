"""
geom3d.py — 3D 几何与投影的"地基"模块

这个文件只做一件事：把三维空间里的点，变成二维屏幕上的点。
理解了这三个函数，你就理解了所有 3D 动画的本质：

    rotate(顶点)  ->  让物体转起来
    project(顶点) ->  把 3D 压扁成 2D（透视投影，近大远小）
    depth_sort(面)->  远的先画、近的后画（画家算法，处理遮挡）

坐标约定：x 向右，y 向下，z 向屏幕里（z 越大越远）。
"""
import math
import numpy as np


def rotate(vertices, ax, ay, az):
    """绕 X / Y / Z 轴旋转。ax/ay/az 是弧度。

    旋转矩阵就是中学的三角函数，本质是每个点绕轴转一个角度。
    numpy 的 @ 是矩阵乘法，一次性把几百个点全转完，比 for 循环快得多。
    """
    cx, sx = math.cos(ax), math.sin(ax)
    cy, sy = math.cos(ay), math.sin(ay)
    cz, sz = math.cos(az), math.sin(az)
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    R = Rz @ Ry @ Rx
    return vertices @ R.T


def project(vertices, cx, cy, focal=520, cam_z=7.0, scale=1.0):
    """透视投影：3D -> 2D。

    关键公式：screen = center + point * focal / (point.z + cam_z)
    分母里那个 z 就是"近大远小"的来源——点越远(z 越大)，
    除以的数越大，投影出来的偏移就越小，看起来就越小。
    """
    v = vertices * scale
    z = v[:, 2] + cam_z
    z = np.maximum(z, 0.1)  # 防止除零
    xs = cx + v[:, 0] * focal / z
    ys = cy + v[:, 1] * focal / z
    return xs, ys, z


def depth_sort(faces, vertices_z):
    """画家算法：先画远的，后画近的，近的会盖住远的。

    faces 是 [(顶点索引元组, 颜色), ...]，按每个面的平均深度从大到小排序。
    """
    def avg_z(face):
        idx = face[0]
        return float(np.mean([vertices_z[i] for i in idx]))
    return sorted(faces, key=avg_z, reverse=True)


# ---------- 常用几何体 ----------

def cube(size=1.0):
    """立方体：8 个顶点 + 6 个面。最经典的入门几何体。"""
    s = size
    v = np.array([
        [-s, -s, -s], [s, -s, -s], [s, s, -s], [-s, s, -s],
        [-s, -s, s], [s, -s, s], [s, s, s], [-s, s, s],
    ], dtype=float)
    faces = [
        ((0, 1, 2, 3), 0.30), ((4, 5, 6, 7), 0.55),
        ((0, 1, 5, 4), 0.40), ((2, 3, 7, 6), 0.45),
        ((1, 2, 6, 5), 0.50), ((3, 0, 4, 7), 0.35),
    ]
    edges = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6),
             (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7)]
    return v, faces, edges


def octahedron(size=1.3):
    """正八面体：上下两个尖 + 赤道四个点，8 个三角面。"""
    s = size
    v = np.array([
        [0, -s, 0], [0, s, 0], [-s, 0, 0], [s, 0, 0], [0, 0, -s], [0, 0, s],
    ], dtype=float)
    faces = [
        ((0, 2, 4), 0.45), ((0, 4, 3), 0.55), ((0, 3, 5), 0.40), ((0, 5, 2), 0.50),
        ((1, 4, 2), 0.60), ((1, 3, 4), 0.50), ((1, 5, 3), 0.65), ((1, 2, 5), 0.55),
    ]
    edges = [(0, 2), (0, 3), (0, 4), (0, 5), (1, 2), (1, 3), (1, 4), (1, 5),
             (2, 4), (4, 3), (3, 5), (5, 2)]
    return v, faces, edges


def icosahedron(size=1.25):
    """正二十面体：20 个三角面，最接近球体的规则多面体，转起来很漂亮。"""
    t = (1 + math.sqrt(5)) / 2
    v = np.array([
        [-1, t, 0], [1, t, 0], [-1, -t, 0], [1, -t, 0],
        [0, -1, t], [0, 1, t], [0, -1, -t], [0, 1, -t],
        [t, 0, -1], [t, 0, 1], [-t, 0, -1], [-t, 0, 1],
    ], dtype=float)
    v = v / np.linalg.norm(v[0]) * size
    faces_idx = [
        (0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11),
        (1, 5, 9), (5, 11, 4), (11, 10, 2), (10, 7, 6), (7, 1, 8),
        (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9),
        (4, 9, 5), (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1),
    ]
    faces = [(idx, 0.35 + (i % 5) * 0.07) for i, idx in enumerate(faces_idx)]
    edges = []
    seen = set()
    for tri, _ in faces:
        for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            key = tuple(sorted((a, b)))
            if key not in seen:
                seen.add(key)
                edges.append(key)
    return v, faces, edges


def point_sphere(n=90, radius=1.7):
    """球面均匀撒点——做"数据/网络/连接"这类意象很好用。"""
    pts = []
    golden = math.pi * (3 - math.sqrt(5))
    for i in range(n):
        y = 1 - (i / (n - 1)) * 2
        r = math.sqrt(max(0, 1 - y * y))
        theta = golden * i
        pts.append([math.cos(theta) * r * radius, y * radius,
                    math.sin(theta) * r * radius])
    return np.array(pts, dtype=float)
