#!/usr/bin/env python3
"""fuxi 2026-11-20: home / switcher gestures on the 53f CI kernel (Kerfand 82e4615/968a7c6 fix, ported).

53f's build-ios17-hid-input.py disables NativeHidInput's edge hook ("21H16: edge hook unqualified"). Without it no contact gets
kIOHIDDigitizerEventFromEdgeTip, UIKit's edge type is 0 and SpringBoard's home and switcher gestures fail at once (taps work):
exactly the boot-ci-hangrec symptom. Kerfand checked the 21H16 IOHIDFamily vtables and turned it back on (install() still checks
every slot and leaves the driver alone on a mismatch); fuxi-touch-edge=0 keeps it off.
Usage: touch-edge-on.py DIR...   (every build-ios17-hid-input.py under the DIRs)"""
import pathlib, sys
OFF = "shared=shared.replace(edge_call,'if(false && driver && (touchEnabled || touchOnly))edge::install(driver); // 21H16: edge hook unqualified')"
ON = ("shared=shared.replace(edge_call,'if(driver && (touchEnabled || touchOnly)){unsigned e=1;"
      "PE_parse_boot_argn(\"fuxi-touch-edge\",&e,sizeof(e));if(e)edge::install(driver);}')")
n = 0
for d in sys.argv[1:]:
    for p in pathlib.Path(d).rglob('build-ios17-hid-input.py'):
        t = p.read_text()
        if OFF in t:
            p.write_text(t.replace(OFF, ON)); n += 1; print(p, ': edge hook on')
        elif 'fuxi-touch-edge' in t:
            n += 1; print(p, ': edge hook already on')
        else:
            print(p, ': edge anchor not found', file=sys.stderr)
print('edge hook scripts:', n)
sys.exit(0 if n else 1)
