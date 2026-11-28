#!/usr/bin/env python3
"""Claude+Gemini 2026-11-28 (Gemini 11-27 23:50 option B): the display hand-off thread (serveScanout: the 1179->1080 scanout_scale blit and
its waitUntilCompleted) is a plain pthread at the default timeshare priority, behind the render server's own threads; copy wait (kernel
swap_end -> kickOnce) averages 2-2.6 ms but peaks at 16-21 ms, which pushes those frames into the 30 Hz bucket. The thread now asks for
QOS_CLASS_USER_INTERACTIVE as it starts (the same call the plugin uses at line 166 for its UTILITY row writer). Boot arg
fuxi-scanout-qos=0 keeps the old behaviour for A/B. Usage: fuxi-scanout-qos.py drivers/AdrenoMetal/NativeAdrenoMetalPlugin.mm"""
import sys
from pathlib import Path
p = Path(sys.argv[1]); s = p.read_text()
if 'fuxi-scanout-qos' in s: print('scanout-qos: already'); sys.exit(0)
old = ('        pthread_create(&scanout, &attributes, [](void *arg) -> void * {\n'
       '            Gpu *g = static_cast<Gpu *>(arg);\n'
       '            sleep(3);\n')
assert s.count(old) == 1, ('scanout-qos anchor', s.count(old))
new = old + ('            // fuxi 11-28: the scanout copy must not queue behind the render server (copy wait peaks 16-21 ms); fuxi-scanout-qos=0 = old\n'
             '            if (!bootArgSet("fuxi-scanout-qos=0")) {\n'
             '                const int qrc = pthread_set_qos_class_self_np(QOS_CLASS_USER_INTERACTIVE, 0);\n'
             '                g->mark(qrc == 0 ? 0x68a1 : 0x68a0);\n'
             '            }\n')
s = s.replace(old, new, 1)
p.write_text(s); print('scanout-qos: serveScanout thread at USER_INTERACTIVE')
