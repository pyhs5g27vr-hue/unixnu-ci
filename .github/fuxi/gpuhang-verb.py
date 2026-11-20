#!/usr/bin/env python3
"""fuxi 2026-11-20: GPUHANG test over USB, as "INPUT 47 0000 0000" (op 0x47 = 'G'), so no new verb, parser or CRC change.
QcomXnuUsbDebug.c's INPUT case calls fuxi_gpu_inject_hang() (a740 NativeAdrenoPublish.cpp, a740-stall-hang.patch) before the
touch path; the reply is OK gpuhang (request queued, the hangcheck thread injects it within 500 ms) or ERR nogpu.
Run after add-input-verb.py / fix-input-verb.py.  Usage: gpuhang-verb.py DIR..."""
import pathlib, sys

BLOCK = ('        if (frame->input_op == 0x47u) {   /* fuxi-gpuhang-20261120: stop the GPU CP (hang detect + recover test) */\n'
         '            extern int fuxi_gpu_inject_hang(unsigned mode);\n'
         '            int queued = fuxi_gpu_inject_hang(frame->input_a);\n'
         '            reply_bytes = control_reply_reboot(reply, sizeof(reply), frame, queued ? "OK" : "ERR", queued ? "gpuhang" : "nogpu");\n'
         '            break;\n'
         '        }\n')
ANCHOR = 'case SXNU_CONTROL_VERB_INPUT: {\n'
ok, n = True, 0
for d in sys.argv[1:]:
    for p in pathlib.Path(d).rglob('QcomXnuUsbDebug.c'):
        if p.parent.name != 'kernel' or 'QcomXnuUsbDebug' not in str(p.parent.parent):
            continue
        t = p.read_text()
        if 'fuxi-gpuhang-20261120' in t:
            print(p, ': already'); n += 1; continue
        if t.count(ANCHOR) != 1 or 'control_reply_reboot(' not in t:
            print(p, ': INPUT case anchor count', t.count(ANCHOR), file=sys.stderr); continue
        p.write_text(t.replace(ANCHOR, ANCHOR + BLOCK, 1)); n += 1
        print(p, ': GPUHANG (INPUT 47) added')
sys.exit(0 if ok and n else 1)
