#!/usr/bin/env python3
"""add-input-verb.py <tree>

给 CI 的 QcomXnuUsbDebug 加 INPUT verb（移植作者 15ec 内核里的 USB 手势通道）。

为什么：
  ctl-run.ps1 -Ios 发的是 "INPUT <op:2hex> <a:4hex> <b:4hex>"（op 1=按下/移动, 2=抬起, 3=按键）。
  但 53f1320c 的 sxnu_control_parse_verb 只认固定长度的单词（HELLO/PING/STATUS/...），
  "INPUT 01 0010 0020" 是 19 字符 → 返回 SXNU_CONTROL_VERB_INVALID → frame 被丢弃 → NO REPLY。
  而且 sxnu_control_frame 里没有原始文本，认出来也拿不到 op/a/b。

本脚本做三件事：
  1. QcomUsbControl.h：加 SXNU_CONTROL_VERB_INPUT 枚举
  2. QcomUsbControl.h：sxnu_control_frame 加 input_op/input_a/input_b 字段
  3. QcomUsbControl.h：parse_frame 在识别 INPUT 后解析三个 hex 参数
  4. QcomXnuUsbDebug.c：加 case SXNU_CONTROL_VERB_INPUT 调用 fuxi_control_touch

用法：add-input-verb.py <UniXNU 根目录>   例如 add-input-verb.py out-ios17/fuxi/tree
"""
import re
import sys
from pathlib import Path

if len(sys.argv) < 2:
    sys.exit(__doc__)
TREE = Path(sys.argv[1])
H = TREE / 'device/drivers/QcomXnuUsbDebug/kernel/QcomUsbControl.h'
C = TREE / 'device/drivers/QcomXnuUsbDebug/kernel/QcomXnuUsbDebug.c'

for p in (H, C):
    if not p.is_file():
        sys.exit('缺文件: %s' % p)

# ---------- 1) QcomUsbControl.h ----------
h = H.read_text()
orig_h = h

# 1a) 枚举
OLD_ENUM = '    SXNU_CONTROL_VERB_REBOOT_FASTBOOT\n};'
NEW_ENUM = '    SXNU_CONTROL_VERB_REBOOT_FASTBOOT,\n    SXNU_CONTROL_VERB_INPUT\n};'
if 'SXNU_CONTROL_VERB_INPUT' in h:
    print('  enum 已有 INPUT，跳过')
elif OLD_ENUM in h:
    h = h.replace(OLD_ENUM, NEW_ENUM, 1)
    print('  ✓ enum 加 SXNU_CONTROL_VERB_INPUT')
else:
    # 兜底：在 enum 结尾的 }; 前插入
    m = re.search(r'(enum\s+sxnu_control_verb\s*\{[^}]*?)\n\};', h, re.S)
    if not m:
        sys.exit('找不到 enum sxnu_control_verb')
    h = h[:m.end(1)] + ',\n    SXNU_CONTROL_VERB_INPUT' + h[m.end(1):]
    print('  ✓ enum 加 SXNU_CONTROL_VERB_INPUT（兜底路径）')

# 1b) frame 结构加字段
m = re.search(r'(struct\s+sxnu_control_frame\s*\{)([^}]*?)(\};)', h, re.S)
if not m:
    sys.exit('找不到 struct sxnu_control_frame')
body = m.group(2)
if 'input_op' in body:
    print('  frame 已有 input_op，跳过')
else:
    add = ('\n    /* INPUT verb 的参数（ctl-run.ps1 -Ios 的 "INPUT op a b"，op 1=按下/移动 2=抬起 3=按键）。\n'
           '     * parse_verb 只返回枚举、拿不到原文，所以在这里存三个解析后的值。 */\n'
           '    uint32_t input_op, input_a, input_b;')
    h = h[:m.end(2)] + add + h[m.end(2):]
    print('  ✓ struct sxnu_control_frame 加 input_op/input_a/input_b')

# 1c) parse_verb 认出 INPUT
OLD_RET = '    return SXNU_CONTROL_VERB_INVALID;\n}'
NEW_RET = ('    if (bytes > 6u && text[0] == \'I\' && text[1] == \'N\' && text[2] == \'P\' &&\n'
           '        text[3] == \'U\' && text[4] == \'T\' && text[5] == \' \')\n'
           '        return SXNU_CONTROL_VERB_INPUT;\n'
           '    return SXNU_CONTROL_VERB_INVALID;\n}')
if 'text[0] == \'I\' && text[1] == \'N\'' in h:
    print('  parse_verb 已认 INPUT，跳过')
elif OLD_RET in h:
    h = h.replace(OLD_RET, NEW_RET, 1)
    print('  ✓ parse_verb 认出 "INPUT ..."')
else:
    sys.exit('找不到 parse_verb 的 return SXNU_CONTROL_VERB_INVALID')

# 1d) parse_frame 里解析三个 hex 参数（在 frame->verb = verb; 之后）
ANCHOR = '    frame->verb = verb;'
if 'frame->input_op' in h:
    print('  parse_frame 已解析参数，跳过')
elif ANCHOR in h:
    # 先给 frame 清零（避免旧值残留）
    add = (ANCHOR + '\n'
           '    frame->input_op = 0;\n'
           '    frame->input_a = 0;\n'
           '    frame->input_b = 0;\n'
           '    if (verb == SXNU_CONTROL_VERB_INPUT) {\n'
           '        /* verb 文本形如 "INPUT 01 0010 0020"（hex，宽度 2/4/4）；\n'
           '         * 只解析能解析的部分，缺省为 0，由调用方判断合法性。 */\n'
           '        size_t q = 6u;   /* 跳过 "INPUT " */\n'
           '        uint32_t vals[3] = {0, 0, 0};\n'
           '        unsigned got = 0;\n'
           '        while (q < verb_bytes && got < 3u) {\n'
           '            while (q < verb_bytes && text_verb(q) == \' \') q++;\n'
           '            uint32_t v = 0;\n'
           '            unsigned digits = 0;\n'
           '            while (q < verb_bytes && digits < 8u) {\n'
           '                uint8_t c = text_verb(q);\n'
           '                uint32_t d;\n'
           '                if (c >= \'0\' && c <= \'9\') d = c - \'0\';\n'
           '                else if (c >= \'a\' && c <= \'f\') d = c - \'a\' + 10u;\n'
           '                else if (c >= \'A\' && c <= \'F\') d = c - \'A\' + 10u;\n'
           '                else break;\n'
           '                v = (v << 4) | d; digits++; q++;\n'
           '            }\n'
           '            if (!digits) break;\n'
           '            vals[got++] = v;\n'
           '        }\n'
           '        frame->input_op = vals[0];\n'
           '        frame->input_a = vals[1];\n'
           '        frame->input_b = vals[2];\n'
           '    }')
    h = h.replace(ANCHOR, add, 1)
    print('  ✓ parse_frame 解析 INPUT 参数')
else:
    sys.exit('找不到 frame->verb = verb;')

# 上面用了 text_verb(q) 宏，改成直接访问；同时确认 verb 文本起点变量名
# 实际 parse_frame 里 verb 原文的指针是 p + verb_start，所以在解析块里换成局部指针
h = h.replace('text_verb(q)', 'vtext[q]')
# 在解析块前定义 vtext
h = h.replace(
    '        size_t q = 6u;   /* 跳过 "INPUT " */',
    '        const uint8_t *vtext = p + verb_start;   /* verb 字段原文 */\n'
    '        size_t q = 6u;   /* 跳过 "INPUT " */'
)

if h != orig_h:
    H.write_text(h)
    print('  QcomUsbControl.h 已更新 (%d 字节)' % len(h))
else:
    print('  QcomUsbControl.h 无变化')

# ---------- 2) QcomXnuUsbDebug.c ----------
c = C.read_text()
orig_c = c

# 在 default: return; 之前插入 INPUT case
ANCHOR_C = '    default:\n        return;'
NEW_CASE = '''    case SXNU_CONTROL_VERB_INPUT: {
        /* 作者 15ec 内核的 USB 手势通道：op 1 = 按下/移动到面板像素 (a,b)，op 2 = 抬起，
         * op 3 = 按键掩码（bit0 home, bit1 power）。fuxi_control_touch 由
         * device/package/FuxiTouchProbe.cpp 提供（native_touch_set_sink 设置 gTouchSink 后才有用）。 */
        extern int fuxi_control_touch(unsigned op, unsigned a, unsigned b) __attribute__((weak_import));
        if (!&fuxi_control_touch) {
            reply_bytes = control_reply_reboot(reply, sizeof(reply), frame, "ERR", "notouch");
            break;
        }
        int touch_result = fuxi_control_touch(frame->input_op, frame->input_a, frame->input_b);
        if (touch_result)
            reply_bytes = control_reply_reboot(reply, sizeof(reply), frame, "OK", "done");
        else
            reply_bytes = control_reply_reboot(reply, sizeof(reply), frame, "ERR", "nosink");
        break;
    }
''' + ANCHOR_C

if 'SXNU_CONTROL_VERB_INPUT' in c:
    print('  QcomXnuUsbDebug.c 已有 INPUT case，跳过')
elif ANCHOR_C in c:
    c = c.replace(ANCHOR_C, NEW_CASE, 1)
    print('  ✓ 加 case SXNU_CONTROL_VERB_INPUT')
else:
    print('  ✗ 找不到 default: return;')
    sys.exit(1)

if c != orig_c:
    C.write_text(c)
    print('  QcomXnuUsbDebug.c 已更新 (%d 字节)' % len(c))

print()
print('=== 验证 ===')
for kw in ('SXNU_CONTROL_VERB_INPUT', 'input_op', 'fuxi_control_touch', 'vtext'):
    print('  %s: QcomUsbControl.h=%d  QcomXnuUsbDebug.c=%d' % (
        kw, h.count(kw), c.count(kw)))
