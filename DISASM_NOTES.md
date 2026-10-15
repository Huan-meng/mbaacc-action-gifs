# MBAA.exe 反汇编笔记 (特效渲染相关)

## 工具
- pefile + capstone (x86 32bit), 线性扫描 .text (0x401000, 1.15MB, 385278 条指令)
- 导入调用通过 jmp 桩: `.text` 里 `FF 25 <iat>` (6 字节), 调用点为 `E8 rel32` 指向桩
- IAT 槽位在 .rdata (0x51b000+)

## D3DX 矩阵函数调用桩 (部分)
- 0x4de554 = D3DXMatrixRotationZ (附近按 6 字节递增排列各 D3DX 函数)
- 0x4de56c = D3DXMatrixScaling
- 0x4de578 = D3DXMatrixMultiply
- 0x4de57e = D3DXMatrixTranslation
- 调用统计: MatrixMultiply 205 处, Translation 57, Scaling 35, RotationZ 26

## 精灵变换矩阵构建函数 0x405c70 (到 0x405dbd ret)
- 构建 Scaling / RotationZ / Translation 三个矩阵 (各与单位阵 Multiply 拷贝)
- 调用者: 0x405f0b (在 0x405dc0 函数内) 和 0x41a289

## 精灵绘制函数 0x405dc0 (到 0x4061a0)
- ebp = 当前帧结构;  [ebp+0x38]=offset_x [ebp+0x3c]=offset_y
  [ebp+0x40]=bounds_x1 [ebp+0x44]=bounds_y1 [ebp+0x28..0x34]=bounds_x2/y2 与纹理尺寸
- ebx = 绘制对象;  [ebx+0x20]/[ebx+0x24] = 对象坐标 (或由 0x4058c0/0x405a10 计算)
- [ebx+0x28] = m_mode (bit0=?, bit1=水平翻转; 2/4 = 特殊模式)
- 流程:
  1. 建单位阵 (栈 0x5c..0x98)
  2. call 0x405c70 (变换矩阵构建) ← 参数 [esi+0x28]
  3. D3DXMatrixMultiply(pOut=edi, I, builder结果)   @0x405f21
  4. D3DXMatrixTranslation(pOut=[esp+0x144], 由 offset-bounds 组合出的四个值) @0x405fb4
     四个值: -bounds_x1, -(bounds_x1), (offset_x-bounds_x1), (offset_y-bounds_y1)
  5. 计算四个顶点: fild(角点) * 2.0 (+ 常量 0x53d628) + 对象屏幕坐标 [0x76e7bc]/[0x76e7c0]
  6. call 0x416110 (draw) — 传入两个矩阵
  7. 若 [esi+0x14]!=0 再画一遍, 顶点色 0x9600ff00 (描边, 见字符串 TecCharaDraw_Edge/fEdgeColor)
- 结论: 顶点坐标 = (offset - bounds + [0..w,h]) * 2 + 对象屏幕坐标,
  与现有实现的定位公式一致; 变换矩阵单独传给 draw。

## EF 结构布局 (解析函数 0x408570, 标签比较)
- +0x00 = EFTP (命令)   cmp 0x50544645
- +0x04 = EFNO (参数)   cmp 0x4f4e4645 (经 0x4083a0 转换)
- +0x08 = EFPR 值数组   cmp 0x52504645 (最多 12 个)
- EFST 另有 3 处引用 (0x409a0d/0x40a046/0x40a4cb, AF 解析区)

## 其他发现
- 引擎字符串: TecCharaDraw / TecCharaDrawEx / TecCharaDraw_Edge / fEdgeColor /
  fTexelN / fTexelX (Han6Draw.cpp)
- `.\data\%s effect.txt`: 角色特效覆盖表 (INI: CharaNo_%03d / File1 / File2 /
  GiantFlag / TagType / CharaNum1/2), 不是 EF 语义表
- 角色脚本系统: `.\grp\command\com_txt\%s_cl_%s_%0d.txt`, 键 CommandList/Type/
  CmdSub/Child/%03d_CheckNum/%03d_Type/%03d_P0..P4 (游戏逻辑层, 非动画层)
- 描边二次绘制: 顶点色 0x9600ff00

## 未解决
- EF 命令分发函数未定位 (1..14 的比较链/跳转表都没命中独立函数,
  这些常数在大量状态机里出现, 噪声大)
- 变换矩阵在 draw 内如何作用 (决定缩放的枢轴) 未最终确认
