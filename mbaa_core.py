"""
MBAACC 资源解析核心库 (纯 Python, 依据 github.com/jmgao/framedisplay 源码移植)

覆盖:
  * 0002.p 归档 (FilePacHeaderA 容器, 前 4096 字节滚动 XOR)
  * <CHAR>.HA6 帧数据 (Hantei6DataFile, 4 字节 tag 链)
  * <CHAR>.CG  图集 (BMP Cutter3)
  * <CHAR>.pal 调色板
"""

import os
import struct

# --------------------------------------------------------------------------
# 归档
# --------------------------------------------------------------------------


def decrapt(data, size, xorkey, xormod, begin=0):
    """移植自 mbaacc_pack.cpp: decrapt(). 就地从 begin 解密 min(size,4096) 字节。"""
    key_b = (xormod & 0xFF) or 1
    n = min(size, 4096)
    key = list(xorkey.to_bytes(4, "little"))
    for i in range((n + 3) // 4):
        off = begin + i * 4
        for j in range(4):
            if off + j < len(data):
                data[off + j] ^= key[j]
        for j in range(4):
            key[j] = (key[j] + key_b) & 0xFF


class Pack:
    """MBAACC 的 .p 归档 (0000.p ~ 0008.p)。"""

    def __init__(self, path=None):
        self.path = None
        self._f = None
        self.folders = []          # list[dict(pos, file_start_id, size, name)]
        self.files = []            # list[dict(pos, unk, size, name)]
        self.data_folder_id = 32768
        self.data_start = 0
        self.xor_key = 0
        if path:
            self.open(path)

    def open(self, path):
        self.close()
        p = os.path.abspath(path)
        if not os.path.exists(p):
            # 允许只给目录
            cand = os.path.join(p, "0002.p")
            if os.path.exists(cand):
                p = cand
        self._f = open(p, "rb")
        self.path = p

        head = self._f.read(52)
        magic = head[:16].rstrip(b"\0")
        if not magic.startswith(b"FilePacHeaderA"):
            raise ValueError("不是 MBAACC FilePacHeaderA 归档: %s" % (head[:16],))
        (_flag, xk, table_size, _data_size,
         folder_count, file_count) = struct.unpack_from("<6I", head, 16)

        if folder_count > 10000 or file_count > 10000:
            raise ValueError("归档索引异常 folder=%d file=%d" % (folder_count, file_count))

        # ---- folder index (268 字节/项)
        self.folders = []
        for _ in range(folder_count):
            raw = bytearray(self._f.read(268))
            pos, start_id, size = struct.unpack_from("<3I", raw, 0)
            decrapt(raw, 256, xk, size, begin=12)       # 只解 filename[256]
            name = bytes(raw[12:268]).split(b"\0")[0].decode("latin-1")
            self.folders.append({"pos": pos, "start": start_id, "size": size, "name": name})

        for i, f in enumerate(self.folders):
            if f["name"] == ".\\data":
                self.data_folder_id = i

        # ---- file index (44 字节/项)
        self.files = []
        for _ in range(file_count):
            raw = bytearray(self._f.read(44))
            pos, unk, size = struct.unpack_from("<3I", raw, 0)
            decrapt(raw, 32, xk, size, begin=12)
            name = bytes(raw[12:44]).split(b"\0")[0].decode("latin-1")
            self.files.append({"pos": pos, "unk": unk, "size": size, "name": name})

        self.data_start = table_size
        self.xor_key = xk
        self._by_name = {}
        for i in range(self.data_folder_start(), len(self.files)):
            self._by_name.setdefault(self.files[i]["name"].lower(), i)
        return self

    # ---------------------------------------------------------------
    def data_folder_start(self):
        """'.\\data' 目录下第一个文件在 file index 中的下标。"""
        if self.data_folder_id == 32768:
            return 0
        n = self.folders[self.data_folder_id]["start"]
        folder = self.data_folder_id + 1
        n_end = 0
        while n_end == 0:
            if folder == len(self.folders):
                n_end = len(self.files)
            else:
                n_end = self.folders[folder]["start"]
                folder += 1
        return n

    def data_folder_end(self):
        n = self.data_folder_start()
        idx = self.data_folder_id + 1
        while idx < len(self.folders) and self.folders[idx]["start"] == 0:
            idx += 1
        if idx >= len(self.folders):
            return len(self.files)
        return self.folders[idx]["start"]

    def names(self):
        return [self.files[i]["name"] for i in range(self.data_folder_start(), self.data_folder_end())]

    def has(self, name):
        return name.lower() in self._by_name

    def read(self, name):
        """按文件名读取并解密, 不存在返回 None。"""
        i = self._by_name.get(name.lower())
        if i is None:
            return None
        ent = self.files[i]
        self._f.seek(self.data_start + ent["pos"])
        data = bytearray(self._f.read(ent["size"]))
        decrapt(data, ent["size"], self.xor_key, 0x03)
        return bytes(data)

    def close(self):
        if self._f:
            self._f.close()
            self._f = None


# --------------------------------------------------------------------------
# .HA6 帧数据
# --------------------------------------------------------------------------

class FrameAF:
    """渲染帧属性 (AF 块)。"""
    __slots__ = ("active", "sprite", "sprite_unk", "offset_x", "offset_y", "duration",
                 "AFF", "blend_mode", "alpha", "red", "green", "blue",
                 "z_rotation", "y_rotation", "x_rotation", "has_zoom", "zoom_x", "zoom_y",
                 "AFJP", "EF", "IF")

    def __init__(self):
        self.active = True
        self.sprite = -1
        self.sprite_unk = -1
        self.offset_x = 0
        self.offset_y = 8
        self.duration = 1
        self.AFF = -1
        self.blend_mode = 0
        self.alpha = 255
        self.red = 255
        self.green = 255
        self.blue = 255
        self.z_rotation = 0.0
        self.y_rotation = 0.0
        self.x_rotation = 0.0
        self.has_zoom = False
        self.zoom_x = 1.0
        self.zoom_y = 1.0
        self.AFJP = -1
        self.EF = []       # list[FrameEF]
        self.IF = []       # list[FrameIF]


class FrameEF:
    __slots__ = ("command", "parameter", "values", "slot")

    def __init__(self):
        self.slot = 0
        self.command = 0
        self.parameter = 0
        self.values = []


class FrameIF:
    __slots__ = ("command", "values", "slot")

    def __init__(self):
        self.slot = 0
        self.command = 0
        self.values = []


class Frame:
    __slots__ = ("AF", "hitboxes", "has_AT", "AT", "stand_state", "speed_flags",
                 "speed_horz", "speed_vert", "accel_horz", "accel_vert")

    def __init__(self):
        self.AF = FrameAF()
        self.hitboxes = {}      # index -> (x1,y1,x2,y2)
        self.has_AT = False
        self.AT = {}
        self.stand_state = 0
        self.speed_flags = 0
        self.speed_horz = 0
        self.speed_vert = 0
        self.accel_horz = 0
        self.accel_vert = 0


class Sequence:
    def __init__(self):
        self.name = ""
        self.move_name = None
        self.move_meter = 0
        self.is_move = False
        self.frames = []
        self.subframe_count = 0
        self.initialized = False
        self.nEF = 0
        self.nIF = 0

    def __len__(self):
        return len(self.frames)


def _u32(b, off):
    return struct.unpack_from("<I", b, off)[0]


def _i32(b, off):
    return struct.unpack_from("<i", b, off)[0]


def _f32(b, off):
    return struct.unpack_from("<f", b, off)[0]


def _tag(b, off):
    return b[off:off + 4]


def _cstr(b):
    """C 风格字符串: 截到首个 NUL, 按 Shift-JIS 解码 (失败则 latin-1)。"""
    raw = bytes(b).split(b"\0")[0]
    try:
        return raw.decode("cp932")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


class FrameData:
    """解析 <CHAR>.HA6 (Hantei6DataFile)。"""

    def __init__(self):
        self.sequences = {}     # seq_id -> Sequence
        self.count = 0

    def load(self, buf):
        if buf is None or len(buf) < 0x28:
            return False
        if not buf.startswith(b"Hantei6DataFile"):
            return False
        if _tag(buf, 0x20) != b"_STR":
            return False
        seq_count = _u32(buf, 0x24)
        if seq_count > self.count:
            self.count = seq_count
        self._main_load(buf, 0x28)
        return True

    # ---- 逐级解析 -------------------------------------------------
    def _main_load(self, b, off):
        end = len(b)
        while off + 4 <= end:
            tag = _tag(b, off)
            off += 4
            if tag == b"PSTR":
                if off + 4 > end:
                    break
                seq_id = _u32(b, off)
                off += 4
                if _tag(b, off) != b"PEND":        # 有内容
                    if seq_id < max(self.count, 65536):
                        seq = self.sequences.get(seq_id)
                        if seq is None:
                            seq = Sequence()
                            self.sequences[seq_id] = seq
                        off = self._sequence_load(b, off, seq)
                else:
                    off += 4
            elif tag == b"_END":
                break
            else:
                off += 4        # 未知 tag, 保守跳过
        return off

    def _sequence_load(self, b, off, seq):
        end = len(b)
        frame_no = 0
        initialized_here = False
        while off + 4 <= end:
            tag = _tag(b, off)
            off += 4
            if tag == b"PTCN":
                off += 5            # 源码按字节前进 (非 4 对齐), 这里保持字节偏移
            elif tag in (b"PSTS", b"PLVL", b"PFLG", b"PDST"):
                off += 4
            elif tag == b"PTT2":
                ln = _u32(b, off)
                if ln < 64:
                    seq.name = _cstr(b[off + 4:off + 4 + ln])
                off += 4 + 4 * ((ln + 3) // 4)
            elif tag == b"PTIT":
                seq.name = _cstr(b[off:off + 32])
                off += 32
            elif tag == b"PDS2":
                nbytes = _u32(b, off)
                if nbytes == 32:
                    nframes = _u32(b, off + 4)
                    nEF = _u32(b, off + 12)
                    nIF = _u32(b, off + 16)
                    seq.nEF = nEF
                    seq.nIF = nIF
                    seq.frames = [Frame() for _ in range(nframes)]
                    seq.initialized = True
                    initialized_here = True
                off += 4 + 4 * (nbytes // 4)
            elif tag == b"FSTR":
                if seq.initialized and frame_no < len(seq.frames):
                    off = self._frame_load(b, off, seq.frames[frame_no], seq)
                    frame_no += 1
                    seq.subframe_count += max(1, seq.frames[frame_no - 1].AF.duration)
            elif tag == b"PEND":
                break
            else:
                off += 4
        if initialized_here and seq.initialized and frame_no < len(seq.frames):
            seq.frames = seq.frames[:frame_no]
            seq.subframe_count = 0
            for f in seq.frames:
                if f.AF.active:
                    seq.subframe_count += max(1, f.AF.duration)
        return off

    def _frame_load(self, b, off, frame, seq):
        end = len(b)
        ef_idx = 0
        while off + 4 <= end:
            tag = _tag(b, off)
            off += 4
            if tag in (b"HRNM", b"HRAT"):
                n = _u32(b, off)
                if tag == b"HRAT":
                    n += 25
                if n <= 32:
                    frame.hitboxes[n] = (_i32(b, off + 4), _i32(b, off + 8),
                                         _i32(b, off + 12), _i32(b, off + 16))
                off += 20
            elif tag in (b"HRNS", b"HRAS"):
                location = _u32(b, off)
                source = _u32(b, off + 4)
                if tag == b"HRAS":
                    location += 25
                if location <= 32:
                    frame.hitboxes[location] = source
                off += 8
            elif tag == b"ATST":
                off = self._AT_load(b, off, frame)
            elif tag == b"ASST":
                off = self._AS_load(b, off, frame)
            elif tag == b"ASSM":
                off += 4
            elif tag == b"AFST":
                off = self._AF_load(b, off, frame.AF)
            elif tag == b"EFST":
                slot = _u32(b, off)
                off += 4
                ef = FrameEF()
                ef.slot = slot
                off = self._EF_load(b, off, ef)
                frame.AF.EF.append(ef)
                ef_idx += 1
            elif tag == b"IFST":
                slot = _u32(b, off)
                off += 4
                it = FrameIF()
                it.slot = slot
                off = self._IF_load(b, off, it)
                frame.AF.IF.append(it)
            elif tag == b"FEND":
                break
            else:
                off += 4
        return off

    def _AT_load(self, b, off, frame):
        frame.has_AT = True
        end = len(b)
        while off + 4 <= end:
            tag = _tag(b, off)
            off += 4
            if tag == b"ATGD":
                frame.AT["guard"] = _u32(b, off); off += 4
            elif tag == b"ATHS":
                frame.AT["proration"] = _u32(b, off); off += 4
            elif tag == b"ATVV":
                red, dmg, unk, circ = struct.unpack_from("<4h", b, off)
                frame.AT.update(red_damage=red, damage=dmg, unknown=unk, circuit_gain=circ)
                off += 8
            elif tag == b"ATHT":
                frame.AT["proration_type"] = _u32(b, off); off += 4
            elif tag == b"ATED":
                break
        return off

    def _AS_load(self, b, off, frame):
        end = len(b)
        while off + 4 <= end:
            tag = _tag(b, off)
            off += 4
            if tag == b"ASV0":
                vals = struct.unpack_from("<5i", b, off)
                frame.speed_flags = vals[0]
                frame.speed_horz = vals[1]
                frame.speed_vert = vals[2]
                frame.accel_horz = vals[3]
                frame.accel_vert = vals[4]
                off += 20
            elif tag == b"ASVX":
                frame.speed_flags = 0x33
            elif tag == b"ASMV":
                off += 4
            elif tag == b"ASS1":
                frame.stand_state = 1
            elif tag == b"ASS2":
                frame.stand_state = 2
            elif tag in (b"ASCN", b"ASCS", b"ASCT"):
                pass
            elif tag == b"ASED":
                break
        return off

    def _AF_load(self, b, off, af):
        end = len(b)
        while off + 4 <= end:
            tag = _tag(b, off)
            off += 4
            if tag == b"AFGP":
                af.sprite_unk = _u32(b, off)
                af.sprite = _i32(b, off + 4)
                off += 8
            elif tag == b"AFOF":
                af.offset_x = _i32(b, off)
                af.offset_y = _i32(b, off + 4)
                off += 8
            elif tag[:3] == b"AFD":
                c = tag[3:4]
                if c.isdigit():
                    af.duration = int(c)
                elif c == b"L":
                    af.duration = _u32(b, off); off += 4
            elif tag[:3] == b"AFY":
                c = tag[3:4]
                if c.isdigit():
                    v = int(c)
                    if v < 4:
                        v += 10
                    af.offset_y = v
                elif c == b"X":
                    af.offset_y = 10
            elif tag[:3] == b"AFF":
                c = tag[3:4]
                if c.isdigit():
                    af.AFF = int(c)
                elif c == b"X":
                    af.AFF = _u32(b, off); off += 4
            elif tag == b"AFAL":
                af.blend_mode = _u32(b, off)
                af.alpha = _u32(b, off + 4)
                off += 8
            elif tag == b"AFRG":
                af.red = _u32(b, off); af.green = _u32(b, off + 4); af.blue = _u32(b, off + 8)
                off += 12
            elif tag == b"AFAZ":
                af.z_rotation = _f32(b, off); off += 4
            elif tag == b"AFAY":
                af.y_rotation = _f32(b, off); off += 4
            elif tag == b"AFAX":
                af.x_rotation = _f32(b, off); off += 4
            elif tag == b"AFZM":
                af.has_zoom = True
                af.zoom_x = _f32(b, off); af.zoom_y = _f32(b, off + 4)
                off += 8
            elif tag == b"AFJP":
                af.AFJP = _u32(b, off); off += 4
            elif tag == b"AFED":
                break
        return off

    def _EF_load(self, b, off, ef):
        end = len(b)
        while off + 4 <= end:
            tag = _tag(b, off)
            off += 4
            if tag == b"EFTP":
                ef.command = _u32(b, off); off += 4
            elif tag == b"EFNO":
                ef.parameter = _u32(b, off); off += 4
            elif tag == b"EFPR":
                cnt = _u32(b, off)
                if cnt <= 12:
                    ef.values = list(struct.unpack_from("<%di" % cnt, b, off + 4))
                off += 4 + 4 * cnt
            elif tag == b"EFED":
                break
        return off

    def _IF_load(self, b, off, it):
        end = len(b)
        while off + 4 <= end:
            tag = _tag(b, off)
            off += 4
            if tag == b"IFTP":
                it.command = _u32(b, off); off += 4
            elif tag == b"IFPR":
                cnt = _u32(b, off)
                if cnt <= 12:
                    it.values = list(struct.unpack_from("<%di" % cnt, b, off + 4))
                off += 4 + 4 * cnt
            elif tag == b"IFED":
                break
        return off


# --------------------------------------------------------------------------
# .CG 图集
# --------------------------------------------------------------------------

class _Align:
    __slots__ = ("x", "y", "width", "height", "source_x", "source_y",
                 "source_image", "copy_flag")


class CG:
    """BMP Cutter3 图集 (含 AACC 追加的 tile 压缩)。"""

    def __init__(self):
        self.data = None
        self.indices = None
        self.n_images = 0
        self.aligns = []
        self.image_table = []      # [ [cell...] ], cell = (start, width, height, offset, type_id, bpp)
        self._cache = {}

    def load(self, buf):
        if buf is None or len(buf) < 0x4F30:
            return False
        if not buf.startswith(b"BMP Cutter3"):
            return False
        self.data = buf
        # C: d = (u32*)(data + 0x10); d += 1; d += 0x800;  -> 0x10 + 4 + 0x800*4
        d = 0x10 + 4 + 0x800 * 4                   # 跳过 1 word + 0x800 words 内嵌调色板
        self.indices = struct.unpack_from("<3001I", buf, d + 12 * 4)
        image_count = _u32(buf, d + 12)
        if image_count >= 2999:
            return False
        align_off = self.indices[3000]
        n_align = (len(buf) - align_off) // 24
        if n_align <= 0:
            return False
        self.aligns = []
        for i in range(n_align):
            o = align_off + i * 24
            a = _Align()
            (a.x, a.y, a.width, a.height,
             a.source_x, a.source_y, a.source_image, a.copy_flag) = struct.unpack_from("<4i4h", buf, o)
            self.aligns.append(a)
        self.n_images = image_count
        self._build_image_table()
        return True

    # ---------------------------------------------------------------
    def image_info(self, n):
        """返回 dict: filename/type_id/width/height/bpp/bounds/align_start/align_len/data_off"""
        if self.data is None or n < 0 or n >= self.n_images:
            return None
        idx = self.indices[n]
        if idx + 76 > len(self.data):
            return None
        (name, type_id, w, h, bpp,
         bx1, by1, bx2, by2, align_start, align_len) = struct.unpack_from("<32s4I4i2I", self.data, idx)
        return {
            "filename": _cstr(name),
            "type_id": type_id, "width": w, "height": h, "bpp": bpp,
            "bounds": (bx1, by1, bx2, by2),
            "align_start": align_start, "align_len": align_len,
            "data_off": idx + 72,
        }

    def _build_image_table(self):
        max_image = 0
        for a in self.aligns:
            if a.source_image > max_image:
                max_image = a.source_image
        max_image += 1
        # cell: [start, width, height, offset, type_id, bpp]
        self.image_table = [[[0, 0, 0, 0, 0, 0] for _ in range(256)] for _ in range(max_image)]

        for i in range(0x3000):
            info = self.image_info(i)
            if info is None:
                continue
            a0 = info["align_start"]
            alen = info["align_len"]
            if a0 + alen > len(self.aligns):
                continue
            address = info["data_off"]
            if info["bpp"] == 32:
                if info["type_id"] == 3:
                    address += 4
                elif info["type_id"] in (2, 4):
                    address += 1024
            for j in range(alen):
                al = self.aligns[a0 + j]
                if al.copy_flag != 0:
                    continue
                w = al.width // 0x10
                h = al.height // 0x10
                x = al.source_x // 0x10
                y = al.source_y // 0x10
                cell_n = (y * 0x10) + x
                if al.source_image >= len(self.image_table):
                    continue
                im = self.image_table[al.source_image]
                if x + w >= 0x10:
                    w = 0x10 - x
                if y + h >= 0x10:
                    h = 0x10 - y
                mult = 4 if info["type_id"] == 1 else 1
                for a in range(h):
                    cell = cell_n + a * 0x10
                    for b in range(w):
                        c = im[cell + b]
                        c[0] = address
                        c[1] = al.width
                        c[2] = al.height
                        c[3] = (b * 0x10) + (a * al.width * 0x10) * mult
                        c[4] = info["type_id"]
                        c[5] = info["bpp"]
                if info["type_id"] == 4:
                    mult = 2
                address += al.width * al.height * mult
            # 每张图的数据块大小 = 所有 align 项之和, 已通过 address 累加

    # ---------------------------------------------------------------
    def sprite(self, n, palette):
        """解码第 n 张图为 RGBA bytes。palette: 256 个 0xAARRGGBB。"""
        key = (n, id(palette))
        info = self.image_info(n)
        if info is None:
            return None
        bx1, by1, bx2, by2 = info["bounds"]
        w = bx2 - bx1
        h = by2 - by1
        if w <= 0 or h <= 0:
            return None

        pal = palette
        custom = None
        if info["bpp"] == 32 and info["type_id"] == 3:
            color = _u32(self.data, info["data_off"]) & 0xFFFFFF
            custom = [0] * 256
            for i in range(1, 256):
                custom[i] = (i << 24) | color
            pal = custom
        elif info["bpp"] == 32 and info["type_id"] == 2:
            # 实测: 这是 type_id==3 的通用版 —— 内嵌 256 项给出 RGB,
            # alpha 取自像素索引本身 (索引 0 透明)。
            # FrameDisplay 源码把它按普通调色板处理并强制 alpha=0xff,
            # 结果是整块不透明黑底 (它的渲染路径根本用不到这些精灵, 属死代码)。
            custom = [0] * 256
            for i in range(1, 256):
                v = _u32(self.data, info["data_off"] + i * 4)
                custom[i] = (i << 24) | (v & 0xFFFFFF)
            custom[0] = 0
            pal = custom
        elif info["bpp"] == 32 and info["type_id"] == 4:
            custom = [0] * 256
            for i in range(256):
                v = _u32(self.data, info["data_off"] + i * 4)
                custom[i] = 0xFF000000 | v
            pal = custom

        out = bytearray(w * h * 4)     # RGBA, 初始全 0
        data = self.data
        dlen = len(data)

        a0 = info["align_start"]
        alen = info["align_len"]
        for j in range(alen):
            al = self.aligns[a0 + j]
            if al.source_image >= len(self.image_table):
                continue
            im = self.image_table[al.source_image]
            cw = al.width // 0x10
            ch = al.height // 0x10
            cx = al.source_x // 0x10
            cy = al.source_y // 0x10
            cell_n = cy * 0x10 + cx

            ty = info["type_id"]
            for a in range(ch):
                base = cell_n + a * 0x10
                for b in range(cw):
                    cell = im[base + b]
                    start, cell_w, cell_h, cell_off, ctype, cbpp = cell
                    if start == 0:
                        continue
                    dx = al.x + b * 0x10 - bx1
                    dy = al.y + a * 0x10 - by1
                    src_off = start + cell_off
                    if src_off + 16 * cell_w > dlen and ctype != 4:
                        # 越界保护
                        if src_off + 16 * 16 > dlen:
                            continue

                    if ty == 4:
                        for c in range(16):
                            yy = dy + c
                            if yy < 0 or yy >= h:
                                continue
                            so = src_off + c * cell_w
                            ao = so + al.width * al.height
                            o = (yy * w + dx) * 4
                            for dd in range(16):
                                xx = dx + dd
                                if xx < 0 or xx >= w:
                                    continue
                                p = pal[data[so + dd]] & 0xFFFFFF
                                alv = data[ao + dd] if ao + dd < dlen else 0
                                px = o + dd * 4
                                out[px] = p & 0xFF
                                out[px + 1] = (p >> 8) & 0xFF
                                out[px + 2] = (p >> 16) & 0xFF
                                out[px + 3] = alv
                    elif ty == 1:
                        for c in range(16):
                            yy = dy + c
                            if yy < 0 or yy >= h:
                                continue
                            so = src_off + c * cell_w * 4
                            o = (yy * w + dx) * 4
                            for dd in range(16):
                                xx = dx + dd
                                if xx < 0 or xx >= w:
                                    continue
                                q = so + dd * 4
                                if q + 4 > dlen:
                                    continue
                                v = _u32(data, q)
                                # 源码是 BGR -> RGB
                                px = o + dd * 4
                                out[px] = (v >> 16) & 0xFF
                                out[px + 1] = (v >> 8) & 0xFF
                                out[px + 2] = v & 0xFF
                                out[px + 3] = (v >> 24) & 0xFF
                    else:
                        for c in range(16):
                            yy = dy + c
                            if yy < 0 or yy >= h:
                                continue
                            so = src_off + c * cell_w
                            o = (yy * w + dx) * 4
                            for dd in range(16):
                                xx = dx + dd
                                if xx < 0 or xx >= w:
                                    continue
                                if so + dd >= dlen:
                                    continue
                                v = pal[data[so + dd]]
                                px = o + dd * 4
                                out[px] = v & 0xFF
                                out[px + 1] = (v >> 8) & 0xFF
                                out[px + 2] = (v >> 16) & 0xFF
                                out[px + 3] = (v >> 24) & 0xFF
        return {"width": w, "height": h, "bounds": (bx1, by1), "rgba": bytes(out)}

    def sprite_name(self, n):
        info = self.image_info(n)
        return info["filename"] if info else None


# --------------------------------------------------------------------------
# 角色
# --------------------------------------------------------------------------

def load_palette(buf):
    """<CHAR>.pal: 36 套 × (4 字节头 + 256 × 4 字节 0x00RRGGBB)"""
    pals = []
    if buf is None:
        return pals
    for i in range(36):
        base = i * 1024 + 4
        if base + 1024 > len(buf):
            break
        raw = struct.unpack_from("<256I", buf, base)
        # C: alpha = v>>24; alpha = (alpha != 0) ? 255 : 0; *p = (v & 0xffffff) | (alpha<<24)
        p = [(v & 0xFFFFFF) | (0xFF000000 if (v >> 24) else 0) for v in raw]
        p[0] &= 0xFFFFFF
        pals.append(p)
    return pals


class Character:
    """一个角色 + 一个月亮 (C/F/H)。"""

    def __init__(self, pack, name, moon=0):
        self.pack = pack
        self.name = name
        self.moon = moon
        self.framedata = FrameData()
        self.cg = CG()
        self.palettes = []

    def load(self):
        pack, name, moon = self.pack, self.name, self.moon
        ok = self.framedata.load(pack.read("%s.HA6" % name))
        pack_extra = ["%s_r.HA6" % name]
        if moon >= 0:
            pack_extra += ["%s_%d.HA6" % (name, moon), "%s_%d_r.HA6" % (name, moon)]
        for f in pack_extra:
            self.framedata.load(pack.read(f))
        if moon >= 0:
            self._load_move_list(pack.read("%s_%d_C.TXT" % (name, moon)))
        self.palettes = load_palette(pack.read("%s.pal" % name))
        if not ok:
            return False
        return True

    def load_graphics(self):
        return self.cg.load(self.pack.read("%s.CG" % self.name))

    def _load_move_list(self, buf):
        if buf is None:
            return
        for line in buf.decode("latin-1").splitlines():
            line = line.strip()
            if line.startswith("//"):
                continue
            if line.startswith("["):
                break
            parts = line.split()
            if len(parts) < 9:
                continue
            try:
                move_id, move_input, p1, p2, move_seq, move_meter = (
                    int(parts[0]), parts[1], parts[2], parts[3], int(parts[4]), int(parts[5]))
            except ValueError:
                continue
            seq = self.framedata.sequences.get(move_seq)
            if seq is None:
                continue
            if len(p1) >= 8 and p1[5] == "0" and p1[6] == "1" and p1[7] == "0":
                move_input = "j." + move_input
            if seq.is_move:
                seq.move_name = (seq.move_name or "") + " " + move_input
            else:
                seq.move_name = move_input
            seq.move_meter = move_meter
            seq.is_move = True

    # ---------------------------------------------------------------
    def sequence_ids(self):
        return sorted(k for k, s in self.framedata.sequences.items() if s.initialized and s.frames)


def name_norm(name):
    return name
