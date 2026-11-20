#!/usr/bin/env python3
"""rstfix for the 53f line (Claude 2026-11-20; same behaviour as the 2026-11-14 f629-rstfix binary patch, e22397cf).

build-fuxi-usb-debug.py injects qcom_reset_request(mode) into QcomXnuUsbDebug.c. For REBOOT-FASTBOOT (mode 1) it first writes the PMIC
bootloader reason over SPMI (br_set_bootloader); when that write fails, or the SPMI windows were never mapped, it returned 0 without any
reset. The QUD caller ignores the result and never clears control_reboot_requested, so the session is poisoned: the request stays
"pending", every later REBOOT is "busy", and only a power-button reset recovers (2026-11-14 f629, 2026-11-17 15ec, 2026-11-20 53f
sbfix-nodylib run-tofb-235242: "REBOOT-FASTBOOT OK state=queued", then 4 minutes on the desktop).
The rstfix: a failed bootloader-flag write falls through to the plain PSCI SYSTEM_RESET, so the phone always resets (to boot_b) and the host
sends REBOOT-FASTBOOT again in the fresh session. The failure code is kept in fuxi_rstfix_result (0 = flag set, -100 = windows not mapped,
otherwise br_set_bootloader's result) for a later look.
Usage: rstfix-qud.py build-fuxi-usb-debug.py...   (every copy; a copy without the reset layer is skipped)"""
import sys

OLD = ("             '    if (mode == 1 && (!reset_obs || !reset_chn ||\\n'\n"
       "             '                      br_set_bootloader(reset_obs, reset_chn, &reset_arb, 0, &before, &after)))\\n'\n"
       "             '        return 0;\\n'\n")
NEW = ("             '    /* fuxi rstfix: a failed bootloader-flag write no longer returns without a reset (poisoned session:\\n'\n"
       "             '     * control_reboot_requested never cleared). Fall through to the plain reset; the host retries. */\\n'\n"
       "             '    if (mode == 1)\\n'\n"
       "             '        fuxi_rstfix_result = (!reset_obs || !reset_chn) ? -100 :\\n'\n"
       "             '            br_set_bootloader(reset_obs, reset_chn, &reset_arb, 0, &before, &after);\\n'\n")
DECL_OLD = "             'int qcom_reset_request(int mode);\\n'\n"
DECL_NEW = "             'volatile int fuxi_rstfix_result;\\n'\n             'int qcom_reset_request(int mode);\\n'\n"

n = 0
for p in sys.argv[1:]:
    try: s = open(p).read()
    except OSError: print(p, ': missing'); continue
    if 'fuxi_rstfix_result' in s: print(p, ': already has rstfix'); n += 1; continue
    if s.count(OLD) != 1 or s.count(DECL_OLD) != 1:
        print(p, ': reset layer not found, unchanged'); continue
    s = s.replace(OLD, NEW, 1).replace(DECL_OLD, DECL_NEW, 1)
    open(p, 'w').write(s); print(p, ': rstfix applied'); n += 1
if not n: raise SystemExit('rstfix: no build-fuxi-usb-debug.py carries the reset layer')
