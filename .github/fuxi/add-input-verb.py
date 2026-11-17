#!/usr/bin/env python3
"""add-input-verb.py <root>

给 CI 的 QcomXnuUsbDebug 加 INPUT verb（移植作者 15ec 内核的 USB 手势通道）。

★ v2：不再假设单一路径。用递归搜索找出 **所有** QcomUsbControl.h / QcomXnuUsbDebug.c
   （workflow 里其它 QUD patch 步骤都用 `find device device-ios17 -path '*QcomXnuUsbDebug/...'`，
   说明可能有多份），对每一份都打补丁并打印。

为什么需要 INPUT verb：
  ctl-run.ps1 -Ios 发 "INPUT <op:2hex> <a:4hex> <b:4hex>"（op 1=按下/移动, 2=抬起, 3=按键）。
  但 sxnu_control_parse_verb 只认固定长度单词，"INPUT 01 0010 0020"（19 字符）返回 INVALID
  → frame 被丢弃 → NO REPLY。而且 sxnu_control_frame 里没有原文，认出来也拿不到 op/a/b。

改五处：
  1. QcomUsbControl.h: enum 加 SXNU_CONTROL_VERB_INPUT
  2. QcomUsbControl.h: frame 加 input_op/input_a/input_b
  3. QcomUsbControl.h: parse_verb 认出 "INPUT "
  4. QcomUsbControl.h: parse_frame 解析三个 hex 参数
  5. QcomXnuUsbDebug.c: 加 case 调 fuxi_control_touch

用法：add-input-verb.py <root>      例如 add-input-verb.py "$GITHUB_WORKSPACE"
"""
import sys
from pathlib import Path

if len(sys.argv) < 2:
    sys.exit(__doc__)
ROOT = Path(sys.argv[1])
if not ROOT.is_dir():
    sys.exit('不是目录: %s' % ROOT)

print('=== 搜索 QcomXnuUsbDebug 源文件（root=%s）===' % ROOT)
HDRS = sorted(ROOT.rglob('QcomXnuUsbDebug/kernel/QcomUsbControl.h'))
SRCS = sorted(ROOT.rglob('QcomXnuUsbDebug/kernel/QcomXnuUsbDebug.c'))
print('  QcomUsbControl.h   : %d 份' % len(HDRS))
for p in HDRS:
    print('    %s' % p)
print('  QcomXnuUsbDebug.c  : %d 份' % len(SRCS))
for p in SRCS:
    print('    %s' % p)
if not HDRS or not SRCS:
    sys.exit('找不到源文件（找 kext 目录名是否不同？）')

# 有些副本可能是 .git 里的（submodule 的 objects），跳过
def skip(p):
    s = str(p)
    return '/.git/' in s or '/objects/' in s


HDRS = [p for p in HDRS if not skip(p)]
SRCS = [p for p in SRCS if not skip(p)]
print()
print('  过滤 .git 之后: h=%d  c=%d' % (len(HDRS), len(SRCS)))


def patch_header(p):
    t = p.read_text(errors='replace')
    orig = t
    changed = []

    # 1) enum
    if 'SXNU_CONTROL_VERB_INPUT' in t:
        changed.append('enum 已有')
    else:
        # 在 REBOOT_FASTBOOT 后面加（可能带逗号或不带）
        for old, new in (
            ('    SXNU_CONTROL_VERB_REBOOT_FASTBOOT\n};',
             '    SXNU_CONTROL_VERB_REBOOT_FASTBOOT,\n    SXNU_CONTROL_VERB_INPUT\n};'),
            ('    SXNU_CONTROL_VERB_REBOOT_FASTBOOT,\n};',
             '    SXNU_CONTROL_VERB_REBOOT_FASTBOOT,\n    SXNU_CONTROL_VERB_INPUT,\n};'),
            ('    SXNU_CONTROL_VERB_REBOOT_FASTBOOT,\n    SXNU_CONTROL_VERB_SWIPE\n};',
             '    SXNU_CONTROL_VERB_REBOOT_FASTBOOT,\n    SXNU_CONTROL_VERB_SWIPE,\n    SXNU_CONTROL_VERB_INPUT\n};'),
        ):
            if old in t:
                t = t.replace(old, new, 1)
                changed.append('enum +INPUT')
                break
        else:
            changed.append('✗ enum 没找到锚点')

    # 2) frame 字段
    if 'input_op' in t:
        changed.append('frame 已有')
    else:
        anchor = '    enum sxnu_control_verb verb;'
        if anchor in t:
            add = (anchor + '\n\n'
                   '    /* INPUT verb 参数（ctl-run.ps1 -Ios 的 "INPUT op a b"）。parse_verb 只返回枚举，\n'
                   '     * 拿不到原文，所以在这里存解析后的三个值。 */\n'
                   '    uint32_t input_op, input_a, input_b;')
            t = t.replace(anchor, add, 1)
            changed.append('frame +input_op/a/b')
        else:
            changed.append('✗ frame 没找到锚点')

    # 3) parse_verb
    if "text[0] == 'I' && text[1] == 'N'" in t:
        changed.append('parse_verb 已有')
    else:
        anchor = '    return SXNU_CONTROL_VERB_INVALID;\n}'
        if anchor in t:
            new = ("    if (bytes > 6u && text[0] == 'I' && text[1] == 'N' && text[2] == 'P' &&\n"
                   "        text[3] == 'U' && text[4] == 'T' && text[5] == ' ')\n"
                   "        return SXNU_CONTROL_VERB_INPUT;\n"
                   + anchor)
            t = t.replace(anchor, new, 1)
            changed.append('parse_verb +INPUT')
        else:
            changed.append('✗ parse_verb 没找到锚点')

    # 4) parse_frame 解析参数
    if 'frame->input_op' in t:
        changed.append('parse_frame 已有')
    else:
        anchor = '    frame->verb = verb;'
        if anchor in t:
            add = (anchor + '\n'
                   '    frame->input_op = 0;\n'
                   '    frame->input_a = 0;\n'
                   '    frame->input_b = 0;\n'
                   '    if (verb == SXNU_CONTROL_VERB_INPUT) {\n'
                   '        /* verb 原文形如 "INPUT 01 0010 0020"（hex）。逐段解析，缺省 0。 */\n'
                   '        const uint8_t *vt = p + verb_start;\n'
                   '        size_t q = 6u;\n'
                   '        uint32_t vals[3] = {0, 0, 0};\n'
                   '        unsigned got = 0;\n'
                   '        while (q < verb_bytes && got < 3u) {\n'
                   '            while (q < verb_bytes && vt[q] == \' \') q++;\n'
                   '            uint32_t v = 0;\n'
                   '            unsigned dg = 0;\n'
                   '            while (q < verb_bytes && dg < 8u) {\n'
                   '                uint8_t ch = vt[q];\n'
                   '                uint32_t dv;\n'
                   '                if (ch >= \'0\' && ch <= \'9\') dv = (uint32_t)(ch - \'0\');\n'
                   '                else if (ch >= \'a\' && ch <= \'f\') dv = (uint32_t)(ch - \'a\' + 10);\n'
                   '                else if (ch >= \'A\' && ch <= \'F\') dv = (uint32_t)(ch - \'A\' + 10);\n'
                   '                else break;\n'
                   '                v = (v << 4) | dv; dg++; q++;\n'
                   '            }\n'
                   '            if (!dg) break;\n'
                   '            vals[got++] = v;\n'
                   '        }\n'
                   '        frame->input_op = vals[0];\n'
                   '        frame->input_a = vals[1];\n'
                   '        frame->input_b = vals[2];\n'
                   '    }')
            t = t.replace(anchor, add, 1)
            changed.append('parse_frame +参数解析')
        else:
            changed.append('✗ parse_frame 没找到锚点')

    if t != orig:
        p.write_text(t)
    return changed, (t != orig)


def patch_source(p):
    t = p.read_text(errors='replace')
    orig = t
    changed = []
    if 'SXNU_CONTROL_VERB_INPUT' in t:
        changed.append('已有 INPUT case')
    else:
        anchor = '    default:\n        return;'
        if anchor in t:
            new = ('    case SXNU_CONTROL_VERB_INPUT: {\n'
                   '        /* 作者 15ec 内核的 USB 手势通道：op 1=按下/移动到面板像素 (a,b)，op 2=抬起，\n'
                   '         * op 3=按键掩码。fuxi_control_touch 由 kits/sheng/FuxiTouchProbe.cpp 提供。 */\n'
                   '        extern int fuxi_control_touch(unsigned op, unsigned a, unsigned b) __attribute__((weak_import));\n'
                   '        if (!&fuxi_control_touch) {\n'
                   '            reply_bytes = control_reply_reboot(reply, sizeof(reply), frame, "ERR", "notouch");\n'
                   '            break;\n'
                   '        }\n'
                   '        int touch_result = fuxi_control_touch(frame->input_op, frame->input_a, frame->input_b);\n'
                   '        if (touch_result)\n'
                   '            reply_bytes = control_reply_reboot(reply, sizeof(reply), frame, "OK", "done");\n'
                   '        else\n'
                   '            reply_bytes = control_reply_reboot(reply, sizeof(reply), frame, "ERR", "nosink");\n'
                   '        break;\n'
                   '    }\n'
                   + anchor)
            t = t.replace(anchor, new, 1)
            changed.append('+INPUT case')
        else:
            changed.append('✗ switch 没找到 default 锚点')
    if t != orig:
        p.write_text(t)
    return changed, (t != orig)


print()
print('=== 打补丁 ===')
for p in HDRS:
    ch, w = patch_header(p)
    print('  h  %s' % p)
    print('     %s%s' % (', '.join(ch), '  [已写入]' if w else '  [无变化]'))
for p in SRCS:
    ch, w = patch_source(p)
    print('  c  %s' % p)
    print('     %s%s' % (', '.join(ch), '  [已写入]' if w else '  [无变化]'))

print()
print('=== 验证（期望 h 每份都有 INPUT 3 次、c 每份 1 次）===')
for p in HDRS:
    t = p.read_text(errors='replace')
    print('  h %-70s VERB_INPUT=%d input_op=%d' % (p.name, t.count('SXNU_CONTROL_VERB_INPUT'), t.count('input_op')))
for p in SRCS:
    t = p.read_text(errors='replace')
    print('  c %-70s VERB_INPUT=%d fuxi_touch=%d' % (p.name, t.count('SXNU_CONTROL_VERB_INPUT'), t.count('fuxi_control_touch')))

print()
print('=== 提醒 ===')
print('  如果 .cache/fuxi-qud-build/libQcomXnuUsbDebug.a 已存在（CI cache 恢复），')
print('  它可能不会被重建。需要确认 kernel 步骤会不会检测源码变化并重编那个库。')
