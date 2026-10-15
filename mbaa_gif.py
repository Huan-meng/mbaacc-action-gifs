# -*- coding: utf-8 -*-
"""
MBAACC 全角色动作 -> GIF 批量导出

用法示例:
    # 列出所有角色
    python mbaa_gif.py --list

    # 导出 C-Akiha 的全部动作(含特效)到 out/gifs/C-AKIHA
    python mbaa_gif.py -c C-AKIHA --effects -o out/gifs

    # 导出所有角色所有月亮形态, 只保留 >=3 帧的动作
    python mbaa_gif.py -c all --effects --min-frames 3 -o out/gifs

    # 只导出指定动作
    python mbaa_gif.py -c C-AKIHA --sequences 0,1,2 --effects

    # 导入 Python 使用
    from mbaa_gif import export_character

参数:
    -c/--characters   all 或逗号分隔的 short name (C-AKIHA) / 文件名 (AKIHA) / long name
    -m/--moon         C,F,H 过滤
    --effects         叠加 EFFECT 特效 (EFTP=8 -> EFFECT 序列)
    --min-frames     跳过帧数过少的动作
    --no-gif          只导出 PNG 序列图 (接触表), 不生成 GIF
    --pad            画面留白
"""

import argparse
import csv
import os
import re
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mbaa_core import Pack, Character
from mbaa_render import (EffectSet, render_sequence, contact_sheet,
                         save_gif, save_apng, save_webp, merge_frames,
                         clear_cache, drop_frames)

# (long_name, short_name, file_name, moon)   -- 摘自 framedisplay/src/mbaacc_framedisplay.cpp
CHARACTERS = [
    ("C Akiha", "C-AKIHA", "AKIHA", 0), ("F Akiha", "F-AKIHA", "AKIHA", 1),
    ("H Akiha", "H-AKIHA", "AKIHA", 2),
    ("C V.Akiha", "C-AKAAKIHA", "AKAAKIHA", 0), ("F V.Akiha", "F-AKAAKIHA", "AKAAKIHA", 1),
    ("H V.Akiha", "H-AKAAKIHA", "AKAAKIHA", 2),
    ("C S.Akiha", "C-S_AKIHA", "S_AKIHA", 0), ("F S.Akiha", "F-S_AKIHA", "S_AKIHA", 1),
    ("H S.Akiha", "H-S_AKIHA", "S_AKIHA", 2),
    ("C Aoko", "C-AOKO", "AOKO", 0), ("F Aoko", "F-AOKO", "AOKO", 1),
    ("H Aoko", "H-AOKO", "AOKO", 2),
    ("C Arcueid", "C-ARC", "ARC", 0), ("F Arcueid", "F-ARC", "ARC", 1),
    ("H Arcueid", "H-ARC", "ARC", 2),
    ("C Warcueid", "C-WARC", "WARC", 0), ("F Warcueid", "F-WARC", "WARC", 1),
    ("H Warcueid", "H-WARC", "WARC", 2),
    ("C Archetype", "C-P_ARC", "P_ARC", 0), ("F Archetype", "F-P_ARC", "P_ARC", 1),
    ("H Archetype", "H-P_ARC", "P_ARC", 2),
    ("C Ciel", "C-CIEL", "CIEL", 0), ("F Ciel", "F-CIEL", "CIEL", 1),
    ("H Ciel", "H-CIEL", "CIEL", 2),
    ("C P.Ciel", "C-P_CIEL", "P_CIEL", 0), ("F P.Ciel", "F-P_CIEL", "P_CIEL", 1),
    ("H P.Ciel", "H-P_CIEL", "P_CIEL", 2),
    ("C Hisui", "C-HISUI", "HISUI", 0), ("F Hisui", "F-HISUI", "HISUI", 1),
    ("H Hisui", "H-HISUI", "HISUI", 2),
    ("C Kouma", "C-KISHIMA", "KISHIMA", 0), ("F Kouma", "F-KISHIMA", "KISHIMA", 1),
    ("H Kouma", "H-KISHIMA", "KISHIMA", 2),
    ("C Kohaku", "C-KOHAKU", "KOHAKU", 0), ("F Kohaku", "F-KOHAKU", "KOHAKU", 1),
    ("H Kohaku", "H-KOHAKU", "KOHAKU", 2),
    ("C Kohaku M", "C-KOHAKU_M", "KOHAKU_M", 0), ("F Kohaku M", "F-KOHAKU_M", "KOHAKU_M", 1),
    ("H Kohaku M", "H-KOHAKU_M", "KOHAKU_M", 2),
    ("C Len", "C-LEN", "LEN", 0), ("F Len", "F-LEN", "LEN", 1),
    ("H Len", "H-LEN", "LEN", 2),
    ("C W.Len", "C-WLEN", "WLEN", 0), ("F W.Len", "F-WLEN", "WLEN", 1),
    ("H W.Len", "H-WLEN", "WLEN", 2),
    ("C M.Hisui", "C-M_HISUI", "M_HISUI", 0), ("F M.Hisui", "F-M_HISUI", "M_HISUI", 1),
    ("H M.Hisui", "H-M_HISUI", "M_HISUI", 2),
    ("C M.Hisui M", "C-M_HISUI_M", "M_HISUI_M", 0), ("F M.Hisui M", "F-M_HISUI_M", "M_HISUI_M", 1),
    ("H M.Hisui M", "H-M_HISUI_M", "M_HISUI_M", 2),
    ("C P.Hisui P", "C-M_HISUI_P", "M_HISUI_P", 0), ("F P.Hisui P", "F-M_HISUI_P", "M_HISUI_P", 1),
    ("H P.Hisui P", "H-M_HISUI_P", "M_HISUI_P", 2),
    ("C Miyako", "C-MIYAKO", "MIYAKO", 0), ("F Miyako", "F-MIYAKO", "MIYAKO", 1),
    ("H Miyako", "H-MIYAKO", "MIYAKO", 2),
    ("C Nanaya", "C-NANAYA", "NANAYA", 0), ("F Nanaya", "F-NANAYA", "NANAYA", 1),
    ("H Nanaya", "H-NANAYA", "NANAYA", 2),
    ("C Neco Arc", "C-NECO", "NECO", 0), ("F Neco Arc", "F-NECO", "NECO", 1),
    ("H Neco Arc", "H-NECO", "NECO", 2),
    ("C Neco Arc P", "C-NECO_P", "NECO_P", 0), ("F Neco Arc P", "F-NECO_P", "NECO_P", 1),
    ("H Neco Arc P", "H-NECO_P", "NECO_P", 2),
    ("C Neco Chaos", "C-NECHAOS", "NECHAOS", 0), ("F Neco Chaos", "F-NECHAOS", "NECHAOS", 1),
    ("H Neco Chaos", "H-NECHAOS", "NECHAOS", 2),
    ("C Nero", "C-NERO", "NERO", 0), ("F Nero", "F-NERO", "NERO", 1),
    ("H Nero", "H-NERO", "NERO", 2),
    ("C Riesbyfe", "C-RIES", "RIES", 0), ("F Riesbyfe", "F-RIES", "RIES", 1),
    ("H Riesbyfe", "H-RIES", "RIES", 2),
    ("C Roa", "C-ROA", "ROA", 0), ("F Roa", "F-ROA", "ROA", 1),
    ("H Roa", "H-ROA", "ROA", 2),
    ("C Ryougi", "C-RYOUGI", "RYOUGI", 0), ("F Ryougi", "F-RYOUGI", "RYOUGI", 1),
    ("H Ryougi", "H-RYOUGI", "RYOUGI", 2),
    ("C Satsuki", "C-SATSUKI", "SATSUKI", 0), ("F Satsuki", "F-SATSUKI", "SATSUKI", 1),
    ("H Satsuki", "H-SATSUKI", "SATSUKI", 2),
    ("C Shiki", "C-SHIKI", "SHIKI", 0), ("F Shiki", "F-SHIKI", "SHIKI", 1),
    ("H Shiki", "H-SHIKI", "SHIKI", 2),
    ("C Sion", "C-SION", "SION", 0), ("F Sion", "F-SION", "SION", 1),
    ("H Sion", "H-SION", "SION", 2),
    ("C V.Sion", "C-V_SION", "V_SION", 0), ("F V.Sion", "F-V_SION", "V_SION", 1),
    ("H V.Sion", "H-V_SION", "V_SION", 2),
    ("C Warakia", "C-WARAKIA", "WARAKIA", 0), ("F Warakia", "F-WARAKIA", "WARAKIA", 1),
    ("H Warakia", "H-WARAKIA", "WARAKIA", 2),
    ("Effect", "EFFECT", "EFFECT", -1),
]

MOON_LABEL = {0: "C", 1: "F", 2: "H", -1: "-"}
BAD = re.compile(r'[\\/:*?"<>|\r\n\t]')

HERE = os.path.dirname(os.path.abspath(__file__))


def _default_pack():
    """按常见位置自动寻找 0002.p, 迁移目录后无需改代码 (也可用 MBAACC_PACK 环境变量)。"""
    cands = [
        os.environ.get("MBAACC_PACK", ""),
        r"c:\Program Files\MBAACC\MBAACC\0002.p",
        r"c:\Program Files (x86)\MBAACC\MBAACC\0002.p",
        os.path.join(HERE, "0002.p"),
        os.path.normpath(os.path.join(HERE, "..", "..", "0002.p")),
        os.path.normpath(os.path.join(HERE, "..", "..", "..", "..", "0002.p")),
        "0002.p",
    ]
    for c in cands:
        if c and os.path.exists(c):
            return os.path.abspath(c)
    return cands[1]


DEFAULT_PACK = _default_pack()
OPAQUE_BG = (24, 24, 40, 255)


def sanitize(s, limit=48):
    s = BAD.sub("_", (s or "").strip())
    s = re.sub(r"\s+", " ", s)
    return (s[:limit] or "unnamed")


def resolve_characters(spec, moon_filter=None):
    if spec is None or spec.lower() == "all":
        sel = list(CHARACTERS)
    else:
        want = [x.strip().lower() for x in spec.split(",") if x.strip()]
        sel = []
        for entry in CHARACTERS:
            if entry[1].lower() in want or entry[2].lower() in want or entry[0].lower() in want:
                sel.append(entry)
        if not sel:
            raise SystemExit("未匹配到角色: %s" % spec)
    if moon_filter:
        allow = set(moon_filter.upper())
        sel = [e for e in sel if MOON_LABEL[e[3]] in allow]
    return sel


def make_effect_catalog(pack, out_dir):
    """渲染全部 EFFECT 序列为图册, 便于人工核对特效映射。"""
    fx = EffectSet(pack)
    out = os.path.join(out_dir, "effect_catalog")
    os.makedirs(out, exist_ok=True)
    idx = []
    done = 0
    for sid in sorted(fx.framedata.sequences.keys()):
        s = fx.framedata.sequences[sid]
        if not s.initialized or not s.frames:
            continue
        try:
            frames, durs = render_sequence(fx, sid, 0, bg=(20, 20, 34, 255))
        except Exception as e:
            idx.append("%3d  ERR %s" % (sid, e))
            continue
        if not frames:
            continue
        sheet = contact_sheet(frames, columns=min(8, len(frames)),
                              bg=(20, 20, 34, 255))
        nm = sanitize(s.name or "noname", 40)
        sheet.convert("RGB").save(os.path.join(out, "EFFECT_%03d_%s.png" % (sid, nm)))
        idx.append("%3d  frames=%-3d sub=%-4d  %s" % (sid, len(frames), sum(durs), s.name))
        done += 1
    with open(os.path.join(out, "index.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(idx))
    print("EFFECT 图册: %d 个 -> %s" % (done, out))


def parse_canvas(spec):
    """'512x896' -> 固定画布 (x0,y0,x1,y1), 单位是游戏单位(输出为 2 倍像素)。
    原点水平居中, 垂直方向上让角色脚下(原点)位于 82% 高度处。"""
    if not spec:
        return None
    w, h = spec.lower().split("x")
    uw, uh = int(w) // 2, int(h) // 2
    x0 = -uw // 2
    y0 = -int(uh * 0.82)
    return (x0, y0, x0 + uw, y0 + uh)


def export_character(pack, entry, out_dir, effects=None, use_effects=False,
                     min_frames=1, sequences=None, pad=8, bg=(24, 24, 40, 255),
                     make_gif=True, verbose=True, on_progress=None, fixed=None,
                     make_sheet=True, alpha_cutoff=32, formats=("gif",)):
    """导出单个角色/月亮形态的全部动作 GIF, 返回统计 dict。"""
    long_name, short_name, file_name, moon = entry
    ch = Character(pack, file_name, moon)
    if not ch.load():
        if verbose:
            print("  [跳过] %s: 帧数据加载失败" % short_name)
        return None
    if not ch.load_graphics():
        if verbose:
            print("  [跳过] %s: %s.CG 加载失败" % (short_name, file_name))
        return None

    sub = os.path.join(out_dir, short_name)
    os.makedirs(sub, exist_ok=True)
    # 大画布的帧会落盘暂存, 避免整段动作的帧同时占内存
    spool = tempfile.mkdtemp(prefix="mbaafx_")

    ids = ch.sequence_ids()
    if sequences:
        ids = [i for i in ids if i in sequences]
    total = 0
    skipped = 0
    rows = []
    for sid in ids:
        seq = ch.framedata.sequences[sid]
        if len(seq.frames) < min_frames:
            skipped += 1
            continue
        fxs = effects if use_effects else None
        try:
            frames, durs = render_sequence(ch, sid, 0, pad=pad,
                                           bg=(None if bg is None else bg),
                                           effects=fxs, fixed=fixed,
                                           spool_dir=spool)
        except Exception as e:
            skipped += 1
            if verbose:
                print("  seq %3d %s 渲染失败: %s" % (sid, seq.name or "", e))
            continue
        if not frames:
            continue
        mframes, mdurs = merge_frames(frames, durs)
        label = seq.name or ("seq%03d" % sid)
        parts = [short_name, "%03d" % sid]
        if seq.move_name:
            parts.append(sanitize(seq.move_name, 24))     # 出招表指令, 如 236A
        parts.append(sanitize(label))
        base = "_".join(parts)
        if make_gif:
            if "gif" in formats:
                save_gif(mframes, mdurs, os.path.join(sub, base + ".gif"), bg=bg,
                         transparent=bg is None, alpha_cutoff=alpha_cutoff)
            if "apng" in formats:
                # APNG 保留完整 alpha 渐变与精确帧时长 (GIF 只有 1 位透明)
                save_apng(mframes, mdurs, os.path.join(sub, base + ".apng.png"))
            if "webp" in formats:
                # 动画 WebP (无损): 完整 alpha 渐变, 体积远小于 APNG
                save_webp(mframes, mdurs, os.path.join(sub, base + ".webp"))
            if "apng" not in formats and "webp" not in formats:
                # 本次不出 APNG, 顺手清掉同名旧文件, 避免残留混淆
                old = os.path.join(sub, base + ".apng.png")
                if os.path.exists(old):
                    try:
                        os.remove(old)
                    except OSError:
                        pass
        if make_sheet:
            contact_sheet(frames, columns=min(8, len(frames))).save(
                os.path.join(sub, base + "_sheet.png"))
        drop_frames(frames)
        total += 1
        rows.append({
            "character": short_name, "file": file_name, "moon": MOON_LABEL[moon],
            "seq": sid, "name": seq.name, "move": seq.move_name or "",
            "frames": len(seq.frames), "subframes": sum(durs),
            "gif_frames": len(mframes), "file_gif": base + ".gif",
        })
        if verbose:
            print("  seq %3d %-10s frames=%-3d gif_frames=%-3d %s" % (
                sid, seq.name or "", len(seq.frames), len(mframes), base))
        if on_progress:
            on_progress(sid)

    shutil.rmtree(spool, ignore_errors=True)
    clear_cache()
    return {"character": short_name, "count": total, "skipped": skipped, "rows": rows}


def main():
    ap = argparse.ArgumentParser(description="MBAACC 动作 GIF 批量导出")
    ap.add_argument("--pack", default=DEFAULT_PACK, help="0002.p 路径")
    ap.add_argument("-c", "--characters", default=None, help="all 或 short/file/long name 列表")
    ap.add_argument("-m", "--moon", default=None, help="月亮形态过滤, 如 C,F,H")
    ap.add_argument("-o", "--out", default="out/gifs", help="输出目录")
    ap.add_argument("--effects", action="store_true",
                    help="叠加共享 EFFECT 特效 (角色自身特效始终渲染)")
    ap.add_argument("--opaque", action="store_true", help="用深色不透明底 (默认透明底)")
    ap.add_argument("--effect-catalog", action="store_true",
                    help="渲染全部 EFFECT 序列图册 (核对特效映射用) 后退出")
    ap.add_argument("--fx-anchor", default="bounds", choices=("bounds", "spawn"),
                    help="共享 EFFECT 精灵的锚点约定: bounds=左上角放在 bounds 偏移处(默认,"
                         "与角色一致, 大量特效位置正确); spawn=精灵中心放在投放点+AF偏移。"
                         "角色自身特效始终用 bounds 约定")
    ap.add_argument("--min-frames", type=int, default=1)
    ap.add_argument("--sequences", default=None, help="只导出这些序列号, 逗号分隔")
    ap.add_argument("--pad", type=int, default=8)
    ap.add_argument("--canvas", default=None,
                    help="固定画布, 如 512x896; 所有动作尺寸一致便于对比 (默认自适应包围盒)")
    ap.add_argument("--format", default="gif",
                    help="输出格式, 逗号分隔: gif / webp / apng (默认 gif)。"
                         "GIF 只有 1 位透明, alpha 渐变会被压成硬边; "
                         "webp(无损)与 apng 保留完整 alpha")
    ap.add_argument("--alpha-cutoff", type=int, default=32,
                    help="GIF 透明阈值: alpha<=该值的像素变透明 (0-255)。"
                         "需要足够低以保留渐隐的特效 (如バッシュ蓄力球 alpha 220->0),"
                         "又要够高以清掉 alpha=1 的占位帧; 默认 32")
    ap.add_argument("--no-gif", action="store_true", help="不生成 GIF (配合 --format 使用)")
    ap.add_argument("--no-sheet", action="store_true", help="不导出 _sheet.png 预览拼图")
    ap.add_argument("-j", "--jobs", type=int, default=8, help="并发进程数 (默认 8)")
    ap.add_argument("--serial", action="store_true", help="强制单进程")
    ap.add_argument("--log", default=None,
                    help="同时把输出以 UTF-8 写入该日志文件 (控制台输出不受影响)")
    ap.add_argument("--list", action="store_true", help="列出角色后退出")
    args = ap.parse_args()

    if args.log:
        lp = os.path.abspath(args.log)
        os.makedirs(os.path.dirname(lp), exist_ok=True)
        fh = open(lp, "w", encoding="utf-8", buffering=1)
        sys.stdout = _Tee(sys.__stdout__, fh)
        sys.stderr = _Tee(sys.__stderr__, fh)

    if args.list:
        for ln, sn, fn, moon in CHARACTERS:
            print("%-16s %-14s file=%-10s moon=%s" % (ln, sn, fn, MOON_LABEL[moon]))
        return

    sel = resolve_characters(args.characters, args.moon)
    seqs = None
    if args.sequences:
        seqs = set(int(x) for x in args.sequences.split(",") if x.strip())

    os.makedirs(args.out, exist_ok=True)
    t0 = time.time()
    print("打开归档: %s" % args.pack)
    pack = Pack(args.pack)
    print("归档内文件数: %d" % len(pack.names()))

    effects = None
    if args.effects:
        effects = EffectSet(pack)
        print("特效资源: %s (EFFECT 序列 %d 个)" % (
            "OK" if effects.is_ready() else "不可用",
            len([1 for k, s in effects.framedata.sequences.items()
                 if s.initialized and s.frames])))

    opts = {
        "out": args.out, "effects": args.effects, "min_frames": args.min_frames,
        "seqs": seqs, "pad": args.pad, "make_gif": not args.no_gif,
        "fixed": parse_canvas(args.canvas), "make_sheet": not args.no_sheet,
        "bg": OPAQUE_BG if args.opaque else None,
        "alpha_cutoff": args.alpha_cutoff,
        "formats": tuple(x.strip().lower() for x in args.format.split(",") if x.strip()),
        "fx_anchor": args.fx_anchor,
    }
    print("背景: %s  透明阈值: %d" % ("深色不透明" if args.opaque else "透明",
                                      args.alpha_cutoff))
    if args.effect_catalog:
        make_effect_catalog(pack, args.out)
        return
    manifest = os.path.join(args.out, "manifest.csv")
    fields = ["character", "file", "moon", "seq", "name", "move",
              "frames", "subframes", "gif_frames", "file_gif"]
    merged = load_manifest(manifest)

    all_rows = []
    njobs = max(1, args.jobs)
    print("待导出: %d 个角色形态, 并发 %d" % (len(sel), njobs if not args.serial else 1))
    sys.stdout.flush()

    done = 0
    t_start = time.time()
    if args.serial or njobs == 1:
        for i, entry in enumerate(sel, 1):
            print("[%d/%d] %s" % (i, len(sel), entry[1]))
            sys.stdout.flush()
            r = export_character(pack, entry, args.out, effects=effects,
                                 use_effects=args.effects, min_frames=args.min_frames,
                                 sequences=seqs, pad=args.pad, make_gif=not args.no_gif,
                                 fixed=opts["fixed"], make_sheet=opts["make_sheet"],
                                 bg=opts["bg"], alpha_cutoff=opts["alpha_cutoff"],
                                 formats=opts["formats"])
            if r:
                all_rows.extend(r["rows"])
                done += 1
                print("      -> %d 个动作 (累计 %d)" % (r["count"], len(all_rows)))
                sys.stdout.flush()
                write_manifest(manifest, merged, all_rows, fields)
    else:
        import multiprocessing as mp
        with mp.Pool(processes=njobs, initializer=_init_worker,
                     initargs=(args.pack, opts)) as pool:
            for i, (name, r) in enumerate(pool.imap_unordered(_run_one, sel), 1):
                if r and r.get("error"):
                    print("[%d/%d] %-14s -> 失败: %s" % (i, len(sel), name, r["error"]))
                    if r.get("trace"):
                        print(r["trace"])
                elif r:
                    all_rows.extend(r["rows"])
                    print("[%d/%d] %-14s -> %d 个动作 (累计 %d, %.0fs)" % (
                        i, len(sel), name, r["count"], len(all_rows),
                        time.time() - t_start))
                else:
                    print("[%d/%d] %-14s -> 跳过" % (i, len(sel), name))
                sys.stdout.flush()
                write_manifest(manifest, merged, all_rows, fields)

    write_manifest(manifest, merged, all_rows, fields)
    print("")
    print("完成: %d 个 GIF, 用时 %.1fs" % (len(all_rows), time.time() - t0))
    print("清单: %s" % manifest)


# --------------------------------------------------------------------------
# 多进程支持
# --------------------------------------------------------------------------

_G = {}


class _Tee:
    """把输出同时写到控制台和日志文件 (各自用自己的编码)。"""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, s):
        for st in self.streams:
            try:
                st.write(s)
            except Exception:
                pass

    def flush(self):
        for st in self.streams:
            try:
                st.flush()
            except Exception:
                pass

    def isatty(self):
        return False


def _init_worker(pack_path, opts):
    import mbaa_render
    mbaa_render.FX_ANCHOR = opts.get("fx_anchor", "bounds")
    _G["pack"] = Pack(pack_path)
    _G["effects"] = EffectSet(_G["pack"]) if opts["effects"] else None
    _G["opts"] = opts


def _run_one(entry):
    o = _G["opts"]
    try:
        r = export_character(_G["pack"], entry, o["out"], effects=_G["effects"],
                             use_effects=o["effects"], min_frames=o["min_frames"],
                             sequences=o["seqs"], pad=o["pad"], make_gif=o["make_gif"],
                             fixed=o["fixed"], make_sheet=o["make_sheet"], verbose=False,
                             bg=o["bg"], alpha_cutoff=o["alpha_cutoff"],
                             formats=o["formats"])
    except Exception as e:
        import traceback
        return entry[1], {"error": "%s: %s" % (type(e).__name__, e),
                          "trace": traceback.format_exc(),
                          "rows": [], "count": 0}
    return entry[1], r


def load_manifest(path):
    merged = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8-sig", newline="") as fh:
                for row in csv.DictReader(fh):
                    merged[(row.get("character"), row.get("file_gif"))] = row
        except Exception:
            merged = {}
    return merged


def write_manifest(path, merged, rows, fields):
    for row in rows:
        merged[(row["character"], row["file_gif"])] = row
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for key in sorted(merged, key=lambda k: (str(k[0]), str(k[1]))):
            w.writerow({f: merged[key].get(f, "") for f in fields})
    os.replace(tmp, path)


if __name__ == "__main__":
    main()
