#!/usr/bin/env python3
"""fuxi 2026-11-20: make the INPUT verb (add-input-verb.py) actually work on the wire. Run after add-input-verb.py.

add-input-verb.py left three gaps, so every "INPUT op a b" frame was dropped (NO REPLY on boot-ci-hangrec):
1. sxnu_control_parse takes the verb up to the first space, so the verb is "INPUT" (5 bytes) and the three arguments sat where the
   CRC must be. Now INPUT is recognised as a 5-byte verb and parse reads " <2hex> <4hex> <4hex>" before the CRC
   (the CRC still covers the whole line before it, as ctl-run.ps1 sends it).
2. sxnu_control_accept / sxnu_control_commit refused every verb past the old last one: INPUT is let through.
3. sxnu_control_verb_name had no "INPUT": the reply carried an empty verb, which ctl-run.ps1 never matches.
Also drops add-input-verb.py's own argument parsing (it read past the 5-byte verb and always produced zeros).
Usage: fix-input-verb.py DIR...   (every QcomXnuUsbDebug/kernel/QcomUsbControl.h under the DIRs)"""
import pathlib, re, sys

def fix(p):
    t = p.read_text(); o = t
    if 'SXNU_CONTROL_VERB_INPUT' not in t:
        print(p, ': no INPUT enum (add-input-verb.py not run?)', file=sys.stderr); return False
    if 'fuxi-input-wire-20261120' in t:
        print(p, ': already fixed'); return True
    # 0) add-input-verb.py's argument block after frame->verb = verb; (always zeros) -> gone
    t = re.sub(r'(    frame->verb = verb;\n)    frame->input_op = 0;\n.*?        frame->input_b = vals\[2\];\n    \}\n?', r'\1', t, count=1, flags=re.S)
    # 1) parse_verb: the 5-byte verb
    m = re.search(r'sxnu_control_parse_verb\(const uint8_t \*text, size_t bytes\)\n\{', t)
    if not m: print(p, ': parse_verb not found', file=sys.stderr); return False
    i = t.index('    return SXNU_CONTROL_VERB_INVALID;\n}', m.end())
    t = t[:i] + ("    /* fuxi-input-wire-20261120 */\n"
                 "    if (bytes == 5u && text[0] == 'I' && text[1] == 'N' && text[2] == 'P' && text[3] == 'U' && text[4] == 'T')\n"
                 "        return SXNU_CONTROL_VERB_INPUT;\n") + t[i:]
    # 1b) parse: arguments between the verb and the CRC
    old = '    if (verb == SXNU_CONTROL_VERB_INVALID) return 0;\n    cursor++;\n    crc_start = cursor;\n'
    if t.count(old) != 1: print(p, ': parse anchor count', t.count(old), file=sys.stderr); return False
    t = t.replace(old,
        '    if (verb == SXNU_CONTROL_VERB_INVALID) return 0;\n'
        '    frame->input_op = frame->input_a = frame->input_b = 0;\n'
        '    if (verb == SXNU_CONTROL_VERB_INPUT) {\n'
        '        static const size_t width[3] = {2u, 4u, 4u};\n'
        '        uint32_t value[3] = {0, 0, 0};\n'
        '        for (unsigned k = 0; k < 3u; ++k) {\n'
        '            uint64_t v = 0;\n'
        '            if (cursor >= bytes || p[cursor] != (uint8_t)\' \') return 0;\n'
        '            cursor++;\n'
        '            if (bytes - cursor < width[k] || !sxnu_control_parse_hex(p + cursor, width[k], &v)) return 0;\n'
        '            cursor += width[k]; value[k] = (uint32_t)v;\n'
        '        }\n'
        '        if (cursor >= bytes || p[cursor] != (uint8_t)\' \') return 0;\n'
        '        frame->input_op = value[0]; frame->input_a = value[1]; frame->input_b = value[2];\n'
        '    }\n'
        '    cursor++;\n    crc_start = cursor;\n', 1)
    # 2) accept / commit range
    n0 = t
    t = re.sub(r'frame->verb > (SXNU_CONTROL_VERB_\w+)\)', r'(frame->verb > \1 && frame->verb != SXNU_CONTROL_VERB_INPUT))', t)
    t = re.sub(r'accepted > (SXNU_CONTROL_VERB_\w+) \|\|', r'(accepted > \1 && accepted != SXNU_CONTROL_VERB_INPUT) ||', t)
    if t == n0: print(p, ': no range checks changed', file=sys.stderr)
    # 3) name
    if 'return "INPUT";' not in t:
        a = '    default: return "";'
        if a not in t: print(p, ': verb_name default not found', file=sys.stderr); return False
        t = t.replace(a, '    case SXNU_CONTROL_VERB_INPUT: return "INPUT";\n' + a, 1)
    p.write_text(t); print(p, ': INPUT wire fixed'); return True

ok, n = True, 0
for d in sys.argv[1:]:
    for p in pathlib.Path(d).rglob('QcomUsbControl.h'):
        if 'QcomXnuUsbDebug' in str(p) and p.parent.name == 'kernel':
            n += 1; ok &= fix(p)
sys.exit(0 if ok and n else 1)
