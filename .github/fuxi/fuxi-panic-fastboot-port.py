#!/usr/bin/env python3
"""fuxi-panic-fastboot-port.py : CI anchor script for QcomXnuUsbDebug.c (Kerfand f0ae963 tree).

Adds boot-arg `fuxi-panic-fastboot=<seconds>` (1..300, off when unset/0):
After `qcom_usb_debug_panic_drain()` finishes draining the panic log and `QCOM PANIC END`,
waits `<seconds>` via CNTVCT/CNTFRQ and calls our existing `qcom_reset_request(1)`
(bootloader / fastboot target), falling back to `platform_smc_reset()` if it returns.

Unlike ljh V2's `fuxi-usb-panic-fastboot.patch`, this uses our kernel's already-linked
`qcom_reset_request(1)` (same symbol used by `SXNU_CONTROL_VERB_REBOOT_FASTBOOT` at L1192),
requiring zero extra reset files and no `-DFUXI_PANIC_FASTBOOT` flag.

Usage:
  python3 fuxi-panic-fastboot-port.py <path/to/QcomXnuUsbDebug.c>
"""
from pathlib import Path
import sys

ANCHOR_HELPER = (
    '    for (;;) __asm__ volatile("wfe" ::: "memory");\n'
    '}\n'
    'static int qcom_usb_control_halt_restart(unsigned int type)\n'
)

REPL_HELPER = (
    '    for (;;) __asm__ volatile("wfe" ::: "memory");\n'
    '}\n'
    'static unsigned int fuxi_panic_fastboot_seconds;\n'
    'static void fuxi_prepare_fastboot(void)\n'
    '{\n'
    '    unsigned int seconds = 0;\n'
    '    if (PE_parse_boot_argn("fuxi-panic-fastboot", &seconds, sizeof(seconds)) && seconds > 0) {\n'
    '        if (seconds > 300u) seconds = 300u;\n'
    '        fuxi_panic_fastboot_seconds = seconds;\n'
    '    }\n'
    '}\n'
    'static void fuxi_panic_fastboot(void)\n'
    '{\n'
    '    extern int qcom_reset_request(int mode);\n'
    '    const unsigned int seconds = fuxi_panic_fastboot_seconds;\n'
    '    if (!seconds) return;\n'
    '    const uint64_t hz = native.status.counter_frequency;\n'
    '    if (hz >= 1000u && hz <= COUNTER_MAX_FREQUENCY) {\n'
    '        const uint64_t start = counter(), wait = (uint64_t)seconds * hz;\n'
    '        while (counter() - start < wait) __asm__ volatile("yield" ::: "memory");\n'
    '    }\n'
    '    (void)qcom_reset_request(1);\n'
    '    platform_smc_reset();\n'
    '}\n'
    'static int qcom_usb_control_halt_restart(unsigned int type)\n'
)

ANCHOR_INIT = (
    '    diag_checkpoint(QCOM_USB_DEBUG_DIAG_ENUM_DONE);\n'
    '    native.status.phase = QCOM_USB_DEBUG_ACTIVE;\n'
)

REPL_INIT = (
    '    diag_checkpoint(QCOM_USB_DEBUG_DIAG_ENUM_DONE);\n'
    '    fuxi_prepare_fastboot();\n'
    '    native.status.phase = QCOM_USB_DEBUG_ACTIVE;\n'
)

ANCHOR_DRAIN_VARS = (
    '    unsigned int iterations = 200000u, marker_queued = 0, announced = 0;\n'
)

REPL_DRAIN_VARS = (
    '    unsigned int iterations = 200000u, marker_queued = 0, announced = 0, drained = 0;\n'
)

ANCHOR_DRAIN_DONE = (
    '        if (marker_queued && dwc3_queued(native.core) == 0 &&\n'
    '            soc_usb_buffer_pending(&usb_log_buffer) == 0) break;\n'
)

REPL_DRAIN_DONE = (
    '        if (marker_queued && dwc3_queued(native.core) == 0 &&\n'
    '            soc_usb_buffer_pending(&usb_log_buffer) == 0) { drained = 1; break; }\n'
)

ANCHOR_DRAIN_OUT = (
    'out:\n'
    '    buffer_status_owned();\n'
    '    release(flags);\n'
    '    if (usb_diag_enabled) diag_reset(10);\n'
)

REPL_DRAIN_OUT = (
    'out:\n'
    '    buffer_status_owned();\n'
    '    release(flags);\n'
    '    if (drained) fuxi_panic_fastboot();\n'
    '    if (usb_diag_enabled) diag_reset(10);\n'
)


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(f"usage: {sys.argv[0]} <QcomXnuUsbDebug.c>")
    p = Path(sys.argv[1])
    s = p.read_text(encoding="utf-8")
    if "fuxi_panic_fastboot_seconds" in s:
        print(f"panic-fastboot: already patched {p}")
        return
    for name, old, new in [
        ("helper", ANCHOR_HELPER, REPL_HELPER),
        ("init", ANCHOR_INIT, REPL_INIT),
        ("drain_vars", ANCHOR_DRAIN_VARS, REPL_DRAIN_VARS),
        ("drain_done", ANCHOR_DRAIN_DONE, REPL_DRAIN_DONE),
        ("drain_out", ANCHOR_DRAIN_OUT, REPL_DRAIN_OUT),
    ]:
        cnt = s.count(old)
        assert cnt == 1, f"{p} [{name}]: expected anchor count==1, got {cnt}"
        s = s.replace(old, new, 1)
    p.write_text(s, encoding="utf-8")
    print(f"panic-fastboot: patched {p} (5/5 anchors)")


if __name__ == "__main__":
    main()
