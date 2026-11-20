#!/usr/bin/env python3
"""fuxi 2026-11-20: two fixes to Kerfand 968's patches/xnu-10063-arm64e/zz-msg-probe.patch.
1. Its first hunk adds #include <ipc/ipc_service_port.h> to osfmk/ipc/ipc_kmsg.c. xnu-10063.141.1 (the tag the build clones) already
   has that line right there, so the hunk's context never matches and the arm64e patch loop stops the kernel build
   ("patch failed: osfmk/ipc/ipc_kmsg.c:115"). Drop only that hunk.
2. Its btmsg probe in ipc_kmsg.c calls proc_pid(), declared only by a header the DEVELOPMENT config pulls in. The RELEASE LTO
   fileset reference build (B12) stops at "call to undeclared function 'proc_pid'" (the docs record the same RELEASE-only
   gap on sheng-vanzhang329). The probe's own block-scope extern line gets proc_pid's declaration next to proc_name_address's,
   on the same line (hunk line counts unchanged). struct proc is declared at file scope in ipc_kmsg.c (proc_best_name), and
   proc_t is struct proc *, so the type matches sys/proc.h wherever both are visible.
Usage: zz-msg-probe-fix.py <zz-msg-probe.patch>"""
import re, sys
p = sys.argv[1]
t = open(p, encoding='utf-8', errors='surrogateescape').read()
hunk = re.compile(r'@@ -115,6 \+115,7 @@[^\n]*\n(?: [^\n]*\n|\+#include <ipc/ipc_service_port\.h>\n)+?(?=@@|diff --git )')
m = hunk.search(t)
if not m:
    print(p, ': ipc_service_port hunk not found (already dropped?)')
else:
    assert '+#include <ipc/ipc_service_port.h>' in m.group(0), m.group(0)
    t = t[:m.start()] + t[m.end():]
    print(p, ': dropped the ipc_service_port.h include hunk (xnu-10063.141.1 has it)')
# 2) proc_pid declaration, inside the ipc_kmsg.c section only
a = t.find('diff --git a/osfmk/ipc/ipc_kmsg.c ')
b = t.find('\ndiff --git ', a + 1) if a >= 0 else -1
sec = t[a:b if b > 0 else len(t)] if a >= 0 else ''
if 'proc_pid(' in sec and 'extern int proc_pid(' not in sec:
    old = 'extern char *proc_name_address(void *p);'
    i = sec.find(old)
    assert i >= 0, 'proc_name_address extern not found in the ipc_kmsg.c section'
    new = sec[:i + len(old)] + ' extern int proc_pid(struct proc *p);   /* fuxi: RELEASE config has no declaration */' + sec[i + len(old):]
    t = t[:a] + new + t[a + len(sec):]
    print(p, ': proc_pid declared for the RELEASE reference build')
else:
    print(p, ': proc_pid: nothing to do')
open(p, 'w', encoding='utf-8', errors='surrogateescape').write(t)
