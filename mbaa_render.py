# -*- coding: utf-8 -*-
"""
MBAACC 动作渲染 + GIF 导出

坐标体系 (依据 mbaacc_character.cpp / texture.cpp):
    角色原点在 CG 虚拟空间 (128, 224)
    精灵左上角(相对角色原点) = (offset_x + bounds_x1 - 128, offset_y + bounds_y1 - 224)
    绘制缩放 = 2x

混合模式 (AFAL 的 blend_mode):
    0    -> 普通 alpha, 颜色 (1,1,1,1)
    1    -> 普通 alpha + 颜色/alpha 调制
    >=2  -> 加法 glBlendFunc(SRC_ALPHA, ONE) + 颜色/alpha 调制

特效 (EF 块):
    EFTP==1 : parameter 是【角色自身 HA6】的序列号, 精灵取自角色 CG, 用角色调色板
              (斩击弧、头发特效、折纸鸟、火柱、命中火花……)
    EFTP==8 : parameter 是【EFFECT.HA6】的序列号, 精灵取自 EFFECT.CG (32bpp 自带颜色)
              (土烟、跳跃环、护盾、冲击波、回路火花等通用特效)
    两种都由 EFPR 的 values[0], values[1] 给出相对角色原点的投放坐标。
    特效从触发的子帧起按自身 duration 播放, 播完消失, 可递归召唤。
"""

import math
import os

import numpy as np
from PIL import Image

ORIGIN_X = 128
ORIGIN_Y = 224
SCALE = 2

EF_CMD_CHAR_EFFECT = 1     # 角色自身序列特效
EF_CMD_PLAY_EFFECT = 8     # 共享 EFFECT 序列特效

# 早期曾把 "AFAL alpha==0" 当作"用默认不透明"处理, 这是错的。
# 共享 EFFECT 里 alpha 语义明确:
#   seq 3  土煙               blend=2 alpha=255     -> 可见的尘土
#   seq 19 着地の砂埃 旧20     blend=2 alpha=32→23   -> 可见, 渐隐
#   seq 20 ＠着地の砂埃 現状使用 blend=1 alpha=0      -> 全透明, 游戏里不显示
#   seq 31 シールドエフェクト   blend=2 alpha=0       -> 不显示
# 即 alpha==0 就是 glColor4f(...,0) 全透明。按字面处理即可, 不再做修正。
FX_ALPHA_ZERO_OPAQUE = False

# 少数动作里存在被放到极远处的精灵/子特效 (游戏里屏幕外不可见),
# 会让联合包围盒暴涨到几千像素并撑爆内存。这里做两步限制:
#   1) 丢弃完全落在原点附近核心区之外的绘制指令
#   2) 把最终画布限制在 MAX_CANVAS_UNITS 以内
# 单位均为"未缩放的游戏单位"(输出像素为其 2 倍)。
CORE_UNITS = 400
MAX_CANVAS_UNITS = 768

# 地面线(相对角色原点, 未缩放游戏单位)。
# MBAA 里有一批名字带「呼び出し/関数」的序列是纯逻辑对象: 它们的图像是假的,
# 被故意放到地面线以下 (如 EX髪呼び出し +94、髪ランダム呼び出し部分 +136、
# 土煙呼び出し関数 +368), 游戏里被地板遮住看不见, 作用只是再召唤真正的特效。
# 不裁剪的话这些假图会出现在画面上, 并把包围盒撑得很高。
EF_GROUND_UNITS = 48

# 共享 EFFECT (cmd=8) 精灵的锚点约定:
#   "bounds" : 与角色精灵相同, 左上角放在 (AF偏移 + bounds偏移 - 原点)   [默认]
#   "spawn"  : 精灵【中心】放在 投放点 + AF偏移
# 实测对照: bounds 约定下 冲刺烟/跳跃环/尘土 等大量共享特效位置正确;
# "spawn" 是为修 バッシュ 引入的, 结果其他特效全部跑位 (已回退)。
# バッシュ 本身改用 FX_SKIP_PARAMS 跳过。
FX_ANCHOR = "bounds"

# alpha 有效值低于该阈值的指令不参与绘制, 也不参与包围盒计算
# (共享 EFFECT 里大量 alpha=0 的占位条目虽然画不出东西, 却会把画布撑得很大)
FX_MIN_ALPHA = 0.004

# 不渲染的特效 (命令, 参数)。
# (8, 26) バッシュ: 内爆蓝色新月 + 角部闪光。EF 数据里它挂在 5B/214A/214B/214C 上,
# 但对照游戏这些招并没有这个视觉特效 (疑似命中/受击时才由逻辑触发, 或是音效类指令),
# 画出来就成了凭空出现的"命中特效", 并且它 94x222 的包围盒会把画布撑得很大。
FX_SKIP_PARAMS = {(8, 26)}

_DRAW_CACHE = {}


# --------------------------------------------------------------------------
# 精灵解码
# --------------------------------------------------------------------------

def decode_sprite(cg, n, palette):
    """解码 CG 第 n 张图为 (PIL.Image, bounds) 或 (None, None)。"""
    if n is None or n < 0:
        return None, None
    key = (id(cg), n, id(palette) if palette is not None else 0)
    hit = _DRAW_CACHE.get(key)
    if hit is not None:
        return hit
    sp = cg.sprite(n, palette)
    if sp is None:
        _DRAW_CACHE[key] = (None, None)
        return None, None
    arr = np.frombuffer(sp["rgba"], dtype=np.uint8).reshape(sp["height"], sp["width"], 4)
    res = (Image.fromarray(arr.copy(), "RGBA"), sp["bounds"])
    _DRAW_CACHE[key] = res
    return res


def clear_cache():
    _DRAW_CACHE.clear()


def scaled(img):
    return img if SCALE == 1 else img.resize((img.width * SCALE, img.height * SCALE), Image.NEAREST)


# --------------------------------------------------------------------------
# 画布
# --------------------------------------------------------------------------

def _unit_transform(has_zoom, zoom_x, zoom_y, z_rotation):
    """返回 2x2 变换矩阵 M (行主序 m11,m12,m21,m22), 与 texture.cpp 的 glRotatef*glScalef 对应。
    旋转/缩放都以角色原点为中心 (GL 里矩阵为恒等, 顶点绕原点变换)。"""
    sx = zoom_x if has_zoom else 1.0
    sy = zoom_y if has_zoom else 1.0
    if z_rotation:
        c = math.cos(z_rotation * 2.0 * math.pi)
        s = math.sin(z_rotation * 2.0 * math.pi)
        # y 轴向下, 用数学上的逆时针矩阵等价于视觉上的顺时针 (与 glRotatef 在 y 翻转投影下一致)
        m11 = c * sx
        m12 = -s * sy
        m21 = s * sx
        m22 = c * sy
    else:
        m11, m12, m21, m22 = sx, 0.0, 0.0, sy
    return (m11, m12, m21, m22)


def _finalize_op(o):
    """补齐变换矩阵与 (变换后) 包围盒, 单位是未缩放的游戏单位。

    变换中心是【角色原点】(即 CG 图集的 128,224)。
    证据: 炎本体/跳跃环 这类全宽条带的 bounds 中心都钉在 CG 原点 128 上,
    带缩放时只有绕角色原点缩放才能保持居中 (脚下火焰环/燃烧带);
    而唯一反例 バッシュ (绕原点会跑到头顶上方) 已用 FX_SKIP_PARAMS 跳过。
    """
    m = _unit_transform(o.get("has_zoom"), o.get("zoom_x", 1.0),
                        o.get("zoom_y", 1.0), o.get("z_rot", 0.0))
    o["m"] = m
    x, y, w, h = o["x"], o["y"], o["w"], o["h"]
    if m == (1.0, 0.0, 0.0, 1.0):
        o["bbox"] = (x, y, x + w, y + h)
    else:
        m11, m12, m21, m22 = m
        xs = []
        ys = []
        for cx, cy in ((x, y), (x + w, y), (x + w, y + h), (x, y + h)):
            xs.append(m11 * cx + m12 * cy)
            ys.append(m21 * cx + m22 * cy)
        o["bbox"] = (min(xs), min(ys), max(xs), max(ys))
    return o


def _op_image(o, ox, oy):
    """按变换把精灵图渲染成目标画布坐标下的图像, 返回 (img, dest_x, dest_y)。"""
    m = o["m"]
    base = scaled(o["img"])
    if m == (1.0, 0.0, 0.0, 1.0):
        return base, (o["x"] + ox) * SCALE, (o["y"] + oy) * SCALE

    m11, m12, m21, m22 = m
    det = m11 * m22 - m12 * m21
    if abs(det) < 1e-9:
        return None, 0, 0
    i11, i12 = m22 / det, -m12 / det
    i21, i22 = -m21 / det, m11 / det

    x0, y0, x1, y1 = o["bbox"]
    dw = max(1, int(round((x1 - x0) * SCALE)))
    dh = max(1, int(round((y1 - y0) * SCALE)))
    cx = (x0 + ox) * SCALE
    cy = (y0 + oy) * SCALE

    # 变换以角色原点为中心:
    #   P_unit = M * p        (p 为未缩放时的单位空间坐标, 含精灵左上角偏移)
    #   p      = M^-1 * P_unit
    #   u,v    = SCALE * (p - 精灵左上角)
    # 目标局部像素 (lx,ly) (从 bbox 左上起算) 对应 P_unit = (x0+lx/SCALE, y0+ly/SCALE)
    c = (i11 * x0 + i12 * y0) - o["x"]
    f = (i21 * x0 + i22 * y0) - o["y"]
    out = base.transform((dw, dh), Image.AFFINE,
                         (i11, i12, c * SCALE, i21, i22, f * SCALE),
                         resample=Image.BILINEAR, fillcolor=(0, 0, 0, 0))
    return out, cx, cy


class Canvas:
    def __init__(self, w, h):
        self.w = w
        self.h = h
        self.px = np.zeros((h, w, 4), dtype=np.float32)

    def blit(self, img, x, y, blend_mode=0, color=(1.0, 1.0, 1.0), alpha=1.0):
        w, h = img.size
        sx0 = max(0, -x); sy0 = max(0, -y)
        dx0 = max(0, x); dy0 = max(0, y)
        sx1 = min(w, self.w - x); sy1 = min(h, self.h - y)
        if sx1 <= sx0 or sy1 <= sy0:
            return
        src = np.asarray(img.crop((sx0, sy0, sx1, sy1)), dtype=np.float32) / 255.0
        if blend_mode != 0:
            src[..., 0] *= color[0]
            src[..., 1] *= color[1]
            src[..., 2] *= color[2]
            src[..., 3] *= alpha
        dst = self.px[dy0:dy0 + (sy1 - sy0), dx0:dx0 + (sx1 - sx0)]
        sa = src[..., 3:4]
        if blend_mode >= 2:
            # 加法混合 (glBlendFunc SRC_ALPHA, ONE)。
            # 游戏里它叠在不透明场景上做提亮; 叠在"空"(透明画布)上时,
            # 单纯抬高 alpha 会得到一块不透明的黑 (源图偏暗的加法层尤其明显)。
            # 所以这里让 alpha 跟随"新增的亮度", 暗的加法层就不会留下黑底。
            s_pre = src[..., :3] * sa
            add_pre = dst[..., :3] * dst[..., 3:4] + s_pre
            lum = s_pre.max(axis=2, keepdims=True)
            out_a = np.clip(dst[..., 3:4] + lum, 0.0, 1.0)
            dst[..., :3] = np.clip(add_pre / np.maximum(out_a, 1e-6), 0.0, 1.0)
            dst[..., 3:4] = out_a
        else:
            out_a = sa + dst[..., 3:4] * (1.0 - sa)
            safe = np.where(out_a > 0, out_a, 1.0)
            dst[..., :3] = (src[..., :3] * sa + dst[..., :3] * dst[..., 3:4] * (1.0 - sa)) / safe
            dst[..., 3:4] = out_a

    def to_image(self, bg=None):
        arr = np.clip(self.px * 255.0 + 0.5, 0, 255).astype(np.uint8)
        img = Image.fromarray(arr, "RGBA")
        if bg is not None:
            base = Image.new("RGBA", img.size, bg)
            base.alpha_composite(img)
            img = base
        return img


# --------------------------------------------------------------------------
# 序列播放器 (特效来源)
# --------------------------------------------------------------------------

class SeqPlayer:
    """在某个 HA6 数据集里按时序播放序列, 供特效逻辑使用。"""

    def __init__(self, framedata, cg, palette, alpha_zero_opaque=False,
                 is_shared=False):
        self.is_shared = is_shared      # 是否共享 EFFECT 数据集 (锚点约定不同)
        self.framedata = framedata
        self.cg = cg
        self.palette = palette
        # 共享 EFFECT 数据里 alpha 写 0 表示"用默认不透明"(如着地の砂埃);
        # 角色自身特效数据里则用 alpha=1 表示"本帧不可见"(如投げのマーク的第0帧),
        # 两者语义不同, 所以这个修正只对 EFFECT 生效。
        self.alpha_zero_opaque = alpha_zero_opaque
        self._starts = {}

    def sequence(self, sid):
        s = self.framedata.sequences.get(sid)
        if s is None or not s.initialized or not s.frames:
            return None
        return s

    def frame_starts(self, sid):
        st = self._starts.get(sid)
        if st is not None:
            return st
        seq = self.sequence(sid)
        if seq is None:
            self._starts[sid] = ([], 0)
            return self._starts[sid]
        starts = []
        t = 0
        for f in seq.frames:
            starts.append(t)
            t += max(1, f.AF.duration)
        self._starts[sid] = (starts, t)
        return self._starts[sid]

    def frame_at(self, sid, t):
        seq = self.sequence(sid)
        if seq is None:
            return None
        starts, total = self.frame_starts(sid)
        if t < 0 or t >= total:
            return None
        lo, hi = 0, len(starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if starts[mid] <= t:
                lo = mid
            else:
                hi = mid - 1
        return seq.frames[lo].AF


class EffectSet:
    """EFFECT.HA6 + EFFECT.CG (32bpp, 无需调色板)。"""

    def __init__(self, pack):
        from mbaa_core import FrameData, CG
        self.framedata = FrameData()
        self.framedata.load(pack.read("EFFECT.HA6"))
        self.cg = CG()
        self.cg.load(pack.read("EFFECT.CG"))
        self.palettes = [None]
        self.player = SeqPlayer(self.framedata, self.cg, None, alpha_zero_opaque=True,
                                is_shared=True)

    def is_ready(self):
        return self.cg.data is not None

    def sequence(self, sid):
        return self.player.sequence(sid)


class FXContext:
    """一个动作渲染期间可用的特效来源集合。

    EFTP==1 的语义是【播放当前帧所在数据集的序列 param】:
      * 角色帧里的 EFTP=1 -> 角色自身 HA6 的序列 (斩击弧/头发/鸟/火柱...)
      * EFFECT 帧里的 EFTP=1 -> EFFECT.HA6 的序列 (土烟调用函数之类)
    早期版本把后者也当成角色序列, 结果共享特效 (如着地の砂埃) 内部再召唤时
    会去角色数据里取到 `頭やられ` 之类的受击动作, 画面上就冒出一帧挨打。
    EFTP==8 则始终指向共享的 EFFECT 数据集。
    """

    def __init__(self, char_player, effect_player=None):
        self.char_player = char_player
        self.effect_player = effect_player

    def child_player(self, command, parent_player):
        if command == EF_CMD_CHAR_EFFECT:
            return parent_player
        if command == EF_CMD_PLAY_EFFECT:
            return self.effect_player
        return None


# --------------------------------------------------------------------------
# 绘制指令
# --------------------------------------------------------------------------

def _make_op(player, sid, t, base_x, base_y):
    af = player.frame_at(sid, t)
    if af is None:
        return None, None
    img, bnd = decode_sprite(player.cg, af.sprite, player.palette)
    if img is None:
        return None, None
    bx1, by1 = bnd
    alpha = af.alpha
    if (FX_ALPHA_ZERO_OPAQUE and player.alpha_zero_opaque
            and alpha == 0 and af.blend_mode == 1):
        alpha = 255
    centered = (FX_ANCHOR == "spawn") and getattr(player, "is_shared", False)
    if centered:
        # 共享 EFFECT: 精灵中心放在 投放点 + AF偏移 (AF偏移是普通位移量, 不减 CG 原点)
        px = base_x + af.offset_x
        py = base_y + af.offset_y
        op_x = px - img.width * 0.5
        op_y = py - img.height * 0.5
    else:
        op_x = base_x + af.offset_x + bx1 - ORIGIN_X
        op_y = base_y + af.offset_y + by1 - ORIGIN_Y
    op = {
        "sprite": af.sprite,
        "x": op_x,
        "y": op_y,
        "w": img.width, "h": img.height, "img": img,
        "blend": af.blend_mode,
        "color": (af.red / 255.0, af.green / 255.0, af.blue / 255.0),
        "alpha": alpha / 255.0,
        "has_zoom": af.has_zoom, "zoom_x": af.zoom_x, "zoom_y": af.zoom_y,
        "z_rot": af.z_rotation,
        "fx": True,
        "center_pivot": centered,
    }
    return op, af


def _new_spawn(player, sid, slot, t0, x, y, depth):
    return {"player": player, "sid": sid, "slot": slot, "t0": t0,
            "t_end": t0 + player.frame_starts(sid)[1],
            "x": x, "y": y, "depth": depth, "children": []}


def _apply_slot_replace(spawns, limit_end=None):
    """EF 槽位语义: 同一槽位后投放的实例会替换掉先前那个。
    不做替换的话, 同一特效被隔几帧重复投放时, 会出现同一动画
    的两个不同阶段同时画在画面上。"""
    by_slot = {}
    for sp in spawns:
        by_slot.setdefault(sp["slot"], []).append(sp)
    for lst in by_slot.values():
        lst.sort(key=lambda s: s["t0"])
        for a, b in zip(lst, lst[1:]):
            if a["t_end"] > b["t0"]:
                a["t_end"] = b["t0"]
    if limit_end is not None:
        for sp in spawns:
            if sp["t_end"] > limit_end:
                sp["t_end"] = limit_end


def _spawns_from_frames(frames, starts, ctx, parent_player, base_x, base_y,
                        t_base, depth, limit_end):
    out = []
    for i, f in enumerate(frames):
        t_abs = t_base + starts[i]
        if limit_end is not None and t_abs >= limit_end:
            break
        for ef in f.AF.EF:
            if (ef.command, ef.parameter) in FX_SKIP_PARAMS:
                continue
            player = ctx.child_player(ef.command, parent_player)
            if player is None:
                continue
            if player.frame_starts(ef.parameter)[1] <= 0:
                continue
            v = ef.values
            out.append(_new_spawn(
                player, ef.parameter, ef.slot, t_abs,
                base_x + (v[0] if len(v) >= 1 else 0),
                base_y + (v[1] if len(v) >= 2 else 0), depth))
    _apply_slot_replace(out, limit_end)
    return out


def _child_spawns(sp, ctx):
    """某特效自身序列里再召唤的子特效。"""
    seq = sp["player"].sequence(sp["sid"])
    if seq is None:
        return []
    starts, _ = sp["player"].frame_starts(sp["sid"])
    return _spawns_from_frames(seq.frames, starts, ctx, sp["player"],
                               sp["x"], sp["y"], sp["t0"], sp["depth"] + 1, sp["t_end"])


def build_spawns(frames, starts, ctx):
    """构建本动作的全部特效实例(展平, 含递归子特效), 已应用槽位替换。"""
    flat = _spawns_from_frames(frames, starts, ctx, ctx.char_player,
                               0, 0, 0, 0, None)
    queue = list(flat)
    guard = 0
    while queue and guard < 60000:
        guard += 1
        sp = queue.pop()
        if sp["depth"] >= 4:
            continue
        kids = _child_spawns(sp, ctx)
        sp["children"] = kids
        flat.extend(kids)
        queue.extend(kids)
    return flat


def collect_subframes(ch, seq, palette, ctx=None):
    """
    返回 (ops_per_subframe, durations)。每个子帧 = 1/60 秒。
    """
    frames = seq.frames
    starts = []
    t = 0
    for f in frames:
        starts.append(t)
        t += max(1, f.AF.duration) if f.AF.active else 1
    total = t

    spawns = build_spawns(frames, starts, ctx) if ctx is not None else []

    nf = len(frames)

    def frame_index(tt):
        lo, hi = 0, nf - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if starts[mid] <= tt:
                lo = mid
            else:
                hi = mid - 1
        return lo

    ops_per = []
    for i in range(total):
        ops = []
        af = frames[frame_index(i)].AF
        if af.active and af.sprite >= 0:
            img, bnd = decode_sprite(ch.cg, af.sprite, palette)
            if img is not None:
                bx1, by1 = bnd
                ops.append(_finalize_op({
                    "sprite": af.sprite,
                    "x": af.offset_x + bx1 - ORIGIN_X,
                    "y": af.offset_y + by1 - ORIGIN_Y,
                    "w": img.width, "h": img.height, "img": img,
                    "blend": af.blend_mode,
                    "color": (af.red / 255.0, af.green / 255.0, af.blue / 255.0),
                    "alpha": af.alpha / 255.0,
                    "has_zoom": af.has_zoom, "zoom_x": af.zoom_x, "zoom_y": af.zoom_y,
                    "z_rot": af.z_rotation,
                    "fx": False,
                }))
        if ctx is not None:
            for sp in spawns:
                if sp["t0"] <= i < sp["t_end"]:
                    op, _ = _make_op(sp["player"], sp["sid"], i - sp["t0"],
                                     sp["x"], sp["y"])
                    if op:
                        ops.append(_finalize_op(op))
        ops_per.append(ops)
    return ops_per, [1] * total


# --------------------------------------------------------------------------
# 渲染
# --------------------------------------------------------------------------

def _load_frame(f):
    """帧可能是 PIL 图像, 也可能是落盘暂存的文件路径。"""
    if isinstance(f, str):
        return Image.open(f)
    return f


def render_sequence(ch, seq_id, palette_idx=0, pad=8, bg=None, effects=None,
                    cache=None, fixed=None, no_effects=False,
                    spool_dir=None, spool_min_pixels=400000):
    """
    渲染一个动作, 返回 (frames[PIL.Image], durations[内部帧数])。

    effects: EffectSet 或 None。为 None 时仍会渲染角色自身的 EFTP=1 特效。
    fixed:   可选 (x0,y0,x1,y1), 单位是游戏单位; 给定时所有动作用同一画布。
    """
    seq = ch.framedata.sequences.get(seq_id)
    if seq is None or not seq.frames:
        return [], []
    pal = ch.palettes[palette_idx] if ch.palettes else None

    ctx = None
    if not no_effects:
        effect_player = effects.player if (effects is not None and effects.is_ready()) else None
        ctx = FXContext(SeqPlayer(ch.framedata, ch.cg, pal), effect_player)

    ops_per, durs = collect_subframes(ch, seq, pal, ctx)

    ops_per = [
        [o for o in ops
         if o["alpha"] > FX_MIN_ALPHA
         and not (o["bbox"][0] > CORE_UNITS or o["bbox"][2] < -CORE_UNITS
                  or o["bbox"][1] > CORE_UNITS or o["bbox"][3] < -CORE_UNITS)
         # 特效完全落到地面线以下 -> 游戏里被地板挡住, 这里也丢掉
         and not (o["fx"] and o["bbox"][1] > EF_GROUND_UNITS)]
        for ops in ops_per
    ]

    if fixed is not None:
        x0, y0, x1, y1 = fixed
        pad = 0
    else:
        x0 = y0 = 1 << 30
        x1 = y1 = -(1 << 30)
        for ops in ops_per:
            for o in ops:
                bb = o["bbox"]
                x0 = min(x0, bb[0]); y0 = min(y0, bb[1])
                x1 = max(x1, bb[2]); y1 = max(y1, bb[3])
        if x0 > x1:
            x0 = y0 = 0
            x1 = y1 = 1
        x0 = max(x0 - pad, -MAX_CANVAS_UNITS)
        y0 = max(y0 - pad, -MAX_CANVAS_UNITS)
        x1 = min(x1 + pad, MAX_CANVAS_UNITS)
        y1 = min(y1 + pad, MAX_CANVAS_UNITS)
        pad = 0

    # 变换后的包围盒是浮点, 这里取整
    x0 = int(math.floor(x0))
    y0 = int(math.floor(y0))
    x1 = int(math.ceil(x1))
    y1 = int(math.ceil(y1))
    if x1 <= x0:
        x1 = x0 + 1
    if y1 <= y0:
        y1 = y0 + 1

    ox = -(x0 - pad)
    oy = -(y0 - pad)
    W = (x1 - x0 + pad * 2) * SCALE
    H = (y1 - y0 + pad * 2) * SCALE

    # 画布大的时候把每帧落盘, 避免整段动作的所有帧同时占内存
    # (大画布下一帧 RGBA 可达 8MB, 上百帧会直接把内存吃光)
    spool = None
    if spool_dir and W * H > spool_min_pixels:
        spool = spool_dir
        os.makedirs(spool, exist_ok=True)

    out = []
    for i, ops in enumerate(ops_per):
        cv = Canvas(W, H)
        for o in ops:
            img, dx, dy = _op_image(o, ox, oy)
            if img is None:
                continue
            cv.blit(img, int(round(dx)), int(round(dy)),
                    blend_mode=o["blend"], color=o["color"], alpha=o["alpha"])
        im = cv.to_image(bg)
        if spool:
            p = os.path.join(spool, "f%05d.png" % i)
            im.save(p, compress_level=1)
            im.close()
            out.append(p)
        else:
            out.append(im)
    return out, durs


def merge_frames(images, durs):
    """合并连续完全相同的帧, 累加时长 (GIF 更小)。"""
    if not images:
        return images, durs
    out_i = [images[0]]
    out_d = [durs[0]]
    prev = np.asarray(_load_frame(images[0]).convert("RGBA"))
    for im, d in zip(images[1:], durs[1:]):
        arr = np.asarray(_load_frame(im).convert("RGBA"))
        if arr.shape == prev.shape and np.array_equal(arr, prev):
            out_d[-1] += d
            if isinstance(im, str):
                try:
                    os.remove(im)
                except OSError:
                    pass
        else:
            out_i.append(im)
            out_d.append(d)
            prev = arr
    return out_i, out_d


def drop_frames(images):
    """清掉落盘暂存的帧文件。"""
    for f in images or ():
        if isinstance(f, str):
            try:
                os.remove(f)
            except OSError:
                pass


def contact_sheet(images, columns=None, bg=(32, 32, 48, 255)):
    if not images:
        return None
    n = len(images)
    columns = columns or min(n, 8)
    rows = (n + columns - 1) // columns
    ims = [_load_frame(i) for i in images]      # 路径形式的帧保持惰性加载
    cw = max(i.width for i in ims)
    chh = max(i.height for i in ims)
    sheet = Image.new("RGBA", (cw * columns, chh * rows), bg)
    for i, im in enumerate(ims):
        r, c = divmod(i, columns)
        sheet.alpha_composite(im.convert("RGBA"), (c * cw, r * chh))
        im.close()
    return sheet


# --------------------------------------------------------------------------
# GIF (支持透明底)
# --------------------------------------------------------------------------

def _gif_frames(images, bg=None, max_colors=255, transparent=True, alpha_cutoff=32):
    """转成 P 模式 GIF 帧。transparent=True 时把 alpha<=cutoff 的像素设为透明索引。"""
    out = []
    for im in images:
        f = _load_frame(im).convert("RGBA")
        if bg is not None:
            base = Image.new("RGBA", f.size, bg)
            base.alpha_composite(f)
            f = base
            alpha = None
        else:
            alpha = np.asarray(f)[..., 3]
        p = f.convert("P", palette=Image.ADAPTIVE, colors=max_colors)
        if transparent and alpha is not None:
            arr = np.asarray(p).copy()
            arr[alpha <= alpha_cutoff] = max_colors          # 保留的透明索引
            pal = list(p.getpalette() or [])
            if len(pal) < 768:
                pal += [0] * (768 - len(pal))
            p = Image.fromarray(arr, "P")
            p.putpalette(pal)
            p.info["transparency"] = max_colors
        out.append(p)
    return out


def save_apng(images, durations, path, fps=60.0, loop=0):
    """APNG: 保留完整的 alpha 渐变 (GIF 只有 1 位透明, 会把渐变压成硬边/纯不透明)。
    帧时长用毫秒浮点, 比 GIF 的 10ms 量化精确。"""
    if not images:
        return False
    ms = [max(10.0, d * 1000.0 / fps) for d in durations]
    frames = [im.convert("RGBA") for im in images]
    frames[0].save(path, save_all=True, append_images=frames[1:],
                   duration=ms, loop=loop, format="PNG",
                   disposal=1, blend=0)
    return True


def save_webp(images, durations, path, fps=60.0, loop=0):
    """动画 WebP (无损): 保留完整的 alpha 渐变 (GIF 只有 1 位透明)。
    帧时长为毫秒浮点, 无 GIF 的 10ms 量化误差。"""
    if not images:
        return False
    ms = [max(10.0, d * 1000.0 / fps) for d in durations]
    frames = [_load_frame(im).convert("RGBA") for im in images]
    frames[0].save(path, save_all=True, append_images=frames[1:],
                   duration=ms, loop=loop, format="WEBP",
                   lossless=True, method=4)
    return True


def save_gif(images, durations, path, fps=60.0, loop=0, bg=None, max_colors=255,
             transparent=True, alpha_cutoff=32):
    # 注意: GIF 帧延时是无符号 16 位 (毫秒, 上限 65535)。
    # 个别动作 (如 WLEN 的胜利姿势) 合并后有超长停顿帧, 会超出上限导致
    # Pillow 抛 "'H' format requires 0 <= number <= 65535", 这里钳到上限。
    if not images:
        return False
    # GIF 帧延时是无符号 16 位 (上限 65535ms)。个别动作 (WLEN 的胜利姿势等)
    # 合并后有超长停顿帧会超出上限, 这里钳住。
    ms = [min(65530, max(20, int(round(d * 1000.0 / fps / 10.0) * 10))) for d in durations]
    frames = _gif_frames(images, bg=bg, max_colors=max_colors,
                         transparent=transparent, alpha_cutoff=alpha_cutoff)
    kw = {}
    if transparent and bg is None:
        kw["transparency"] = max_colors
    frames[0].save(path, save_all=True, append_images=frames[1:],
                   duration=ms, loop=loop, disposal=2, optimize=True, **kw)
    return True
