#!/usr/bin/env python3
"""Claude 2026-11-28: arm the Gunyah watchdog before the modem probe, not only at launchd.
11-28 bbsel boot 1 hung at "FUXI_MODEM: step: the modem image's reset" (display probe, before launchd); in the good boot the reset
step is line 337 and "fuxi hwdt: Gunyah watchdog armed" line 350, so during the hang the watchdog was never armed and the user had
to press the keys. fuxi_hwdt_start() keeps its own once-guard, so the later call from sheng_boot_watchdog_policy returns at once.
Weak reference: if the wrapper is not linked in, the probe just skips it. Usage: fuxi-hwdt-early.py ROOT..."""
import sys
from pathlib import Path
decl = 'extern "C" void native_fuxi_modem_probe(void);'
call = '\tnative_fuxi_modem_probe();\n'
k = 0
for root in sys.argv[1:]:
    for p in sorted(Path(root).rglob('Ios17LegacyDisplayProbe.cpp')):
        s = p.read_text()
        if 'fuxi_hwdt_start_early' in s: print('hwdt-early: already', p); k += 1; continue
        assert s.count(decl) == 1 and s.count(call) == 1, ('hwdt-early anchors', p, s.count(decl), s.count(call))
        s = s.replace(decl, 'extern "C" void fuxi_hwdt_start_early(void) __attribute__((weak));   // claude 11-28: watchdog before the modem\n' + decl, 1)
        s = s.replace(call, '\tif (fuxi_hwdt_start_early) fuxi_hwdt_start_early();\n' + call, 1)
        p.write_text(s); k += 1; print('hwdt-early: patched', p)
assert k >= 1, 'no Ios17LegacyDisplayProbe.cpp with native_fuxi_modem_probe'
