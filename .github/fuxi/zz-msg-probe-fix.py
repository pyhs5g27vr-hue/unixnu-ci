#!/usr/bin/env python3
"""fuxi 2026-11-20: Kerfand 968's patches/xnu-10063-arm64e/zz-msg-probe.patch opens with a hunk that adds
#include <ipc/ipc_service_port.h> to osfmk/ipc/ipc_kmsg.c. xnu-10063.141.1 (the tag the build clones) already has
that line right there, so the hunk's context never matches and the arm64e patch loop stops the kernel build
("patch failed: osfmk/ipc/ipc_kmsg.c:115"). Drop only that hunk; the rest of the probe is unchanged.
Usage: zz-msg-probe-fix.py <zz-msg-probe.patch>"""
import re, sys
p = sys.argv[1]
t = open(p, encoding='utf-8', errors='surrogateescape').read()
hunk = re.compile(r'@@ -115,6 \+115,7 @@[^\n]*\n(?: [^\n]*\n|\+#include <ipc/ipc_service_port\.h>\n)+?(?=@@|diff --git )')
m = hunk.search(t)
if not m:
    print(p, ': ipc_service_port hunk not found (already dropped?)'); sys.exit(0)
assert '+#include <ipc/ipc_service_port.h>' in m.group(0), m.group(0)
t = t[:m.start()] + t[m.end():]
open(p, 'w', encoding='utf-8', errors='surrogateescape').write(t)
print(p, ': dropped the ipc_service_port.h include hunk (xnu-10063.141.1 has it)')
